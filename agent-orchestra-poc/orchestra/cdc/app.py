import asyncio
import logging
import threading
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from orchestra.cdc.consumer import Consumer
from orchestra.cdc.cursors import CursorStore
from orchestra.cdc.gateway_client import GatewayClient, check_token
from orchestra.cdc.hub import Hub
from orchestra.cdc.scheduler import Scheduler
from orchestra.cdc.settings import CdcSettings
from orchestra.cdc.source import CdcSource

log = logging.getLogger("orchestra.cdc")


def build(settings: CdcSettings, hub: Hub | None = None, gw: GatewayClient | None = None):
    hub = hub or Hub()
    gw = gw or GatewayClient(settings.gateway_url, settings.sys_token)
    source = CdcSource(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    cursors = CursorStore(settings.data_dir / "cursors.json")
    consumer = Consumer(settings, source, gw, cursors, hub)
    return consumer, Scheduler(settings, gw, hub), hub


def create_app(settings: CdcSettings | None = None, autostart: bool = True, consumer=None, scheduler=None, hub=None) -> FastAPI:
    settings = settings or CdcSettings.from_env()
    if consumer is None:
        consumer, scheduler, hub = build(settings, hub)
    auth_http = httpx.Client(base_url=settings.gateway_url, timeout=5)
    stop = threading.Event()

    def sched_loop():
        while not stop.is_set():
            try:
                scheduler.tick()
            except Exception as e:
                log.error("scheduler: %s", type(e).__name__)
            stop.wait(settings.scheduler_interval)

    @asynccontextmanager
    async def lifespan(app):
        threads = []
        if autostart:
            threads = [threading.Thread(target=consumer.run, args=(stop,), daemon=True),
                       threading.Thread(target=sched_loop, daemon=True)]
            for t in threads:
                t.start()
        yield
        stop.set()
        for t in threads:
            t.join(timeout=3)

    app = FastAPI(title="Orchestra CDC consumer", lifespan=lifespan)
    app.state.consumer, app.state.hub = consumer, hub

    @app.get("/health")
    def health():
        return {"ok": True, "cursors": {db: bool(consumer.cursors.get(db)) for db in settings.dbs}}

    @app.get("/stats")
    def stats():
        return {**consumer.stats.snapshot(), "scheduler": {"fired": scheduler.fired, "skipped": scheduler.skipped}}

    async def _auth(ws: WebSocket, kinds: tuple[str, ...]):
        token = ws.query_params.get("token") or ws.headers.get("authorization", "").removeprefix("Bearer ").strip()
        who = await run_in_threadpool(check_token, auth_http, token) if token else None
        if not who or who["kind"] not in kinds:
            await ws.close(code=4401)
            return None
        await ws.accept()
        return who

    async def _pump(ws: WebSocket, register, replay=()):
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        cb = register(lambda *a: loop.call_soon_threadsafe(q.put_nowait, a))
        try:
            for item in replay:
                await ws.send_json(item)
            while True:
                recv = asyncio.create_task(ws.receive_text())
                get = asyncio.create_task(q.get())
                done, pending = await asyncio.wait({recv, get}, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
                if recv in done:
                    recv.result()          # client message ignored; a disconnect raises WebSocketDisconnect
                if get in done:
                    yield get.result()
        except WebSocketDisconnect:
            pass
        finally:
            hub.off(cb)

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        """Normalized stream {t, type, actor, target, payload}, identical live and (phase 6) in replay."""
        if await _auth(ws, ("user", "admin", "svc")) is None:
            return
        async for (ev,) in _pump(ws, hub.on_event, replay=list(hub.history)):
            await ws.send_json(ev)

    @app.websocket("/ws/wake")
    async def ws_wake(ws: WebSocket):
        """Runtime wake-up: it only receives wake-ups for its own agent (identity taken from the token)."""
        who = await _auth(ws, ("svc",))
        if who is None:
            return
        await ws.send_json({"type": "hello", "agent": who["id"]})
        async for agent_id, info in _pump(ws, hub.on_wake):
            if agent_id == who["id"]:
                await ws.send_json({"type": "wake", **info})

    return app
