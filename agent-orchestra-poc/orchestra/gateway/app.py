import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orchestra.gateway.ctx import Ctx, default_llm_factory
from orchestra.gateway.errors import ApiError
from orchestra.gateway.keystore import KeyStore
from orchestra.gateway.routes import admin, core, internal, kg, llm, memory, replay, routines, support, tools, ui
from orchestra.gateway.settings import Settings
from orchestra.gateway.store import Store

log = logging.getLogger("orchestra.gateway")


def create_app(settings: Settings | None = None, llm_factory=None) -> FastAPI:
    settings = settings or Settings.from_env()
    ctx = Ctx(settings, Store(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, settings.db,
                    kg_auth=(settings.kg_user, settings.kg_password)),
              KeyStore(settings.data_dir, settings.master_key, settings.env_llm_key),
              llm_factory or default_llm_factory(settings))

    @asynccontextmanager
    async def lifespan(app):
        yield
        ctx.store.close()

    app = FastAPI(title="Orchestra gateway", lifespan=lifespan)
    app.state.ctx = ctx

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse({"error": e.code, "detail": e.detail}, status_code=e.status)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception):
        log.error("erreur interne : %s", type(e).__name__, exc_info=bool(__import__("os").environ.get("ORCHESTRA_DEBUG")))  # jamais de corps de requête ni de secret dans les journaux
        return JSONResponse({"error": "internal", "detail": type(e).__name__}, status_code=500)

    @app.get("/health")
    def health():
        return {"ok": True}

    for m in (core, memory, tools, kg, admin, llm, routines, internal, support, ui, replay):
        app.include_router(m.router)
    return app
