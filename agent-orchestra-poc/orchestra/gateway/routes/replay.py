"""Relecture : le flux d'événements est reconstruit depuis le graphe (chaque changement d'état garde sa date).
L'interface reçoit le même format normalisé qu'en direct et ne voit pas la différence."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from orchestra.gateway.auth import Principal, get_ctx, require_admin
from orchestra.gateway.errors import NotFound
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.routes.ui import require_ui
from orchestra.gateway.store import to_json
from pydantic import Field

router = APIRouter()
RANK = {"sent": 0, "woken": 1, "waiting": 2, "tool.start": 3, "status": 3, "learned": 4, "vote": 4, "tool.end": 5, "error": 5, "idle": 6}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def reconstruct(ctx, t_from: str | None = None, t_to: str | None = None, limit: int = 5000) -> list[dict]:
    rows = ctx.store.read(lambda r: r.all("replay_events", **{"from": t_from or "1970-01-01T00:00:00Z", "to": t_to or "2999-01-01T00:00:00Z"}, limit=limit))
    events = []
    for x in to_json(rows):
        payload = {k: v for k, v in x["payload"].items() if v is not None}
        pj = payload.pop("pj", None)
        if pj:
            kind = (json.loads(pj) or {}).get("kind")
            if kind:
                payload["kind"] = kind                     # même charge utile que le flux en direct (pour les chapitres)
        events.append({"t": x["t"], "type": x["type"], "actor": x["actor"], "target": x["target"], "payload": payload})
    events.sort(key=lambda e: (e["t"], RANK.get(e["type"], 9)))
    return events


def _window(ctx, run_id: str | None, t_from: str | None, t_to: str | None):
    if run_id:
        run = ctx.store.read(lambda r: r.one("run_get", id=run_id))
        if run is None:
            raise NotFound("recording not found")
        run = to_json(run)
        return run, run["startedAt"], run["endedAt"] or t_to
    return None, t_from, t_to


@router.get("/replay/events")
def replay_events(runId: str | None = None, since: str | None = None, until: str | None = None,
                  p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    run, a, b = _window(ctx, runId, since, until)
    events = reconstruct(ctx, a, b)
    return {"run": run, "from": a, "to": b, "events": events}


@router.get("/replay/runs")
def list_runs(p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    return {"runs": to_json(ctx.store.read(lambda r: r.all("runs_list")))}


class NewRun(Strict):
    name: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    chainId: str | None = None


@router.post("/replay/runs", status_code=201)
def start_run(b: NewRun, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Marque le début d'un enregistrement : la relecture lira les événements de la fenêtre [début, fin]."""
    row = ctx.store.write({"agentId": p.id, "chainId": b.chainId or "none"}, lambda r: r.one(
        "run_create", id=uuid.uuid4().hex[:12], runName=b.name, note=b.note, chainId=b.chainId, by=p.id))
    return to_json(row)


@router.post("/replay/runs/{run_id}/end")
def end_run(run_id: str, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one("run_end", id=run_id))
    if row is None:
        raise NotFound("recording not found")
    return to_json(row)


def _dir(ctx) -> Path:
    d = Path(ctx.settings.recordings_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


class Export(Strict):
    slug: str


@router.post("/replay/runs/{run_id}/export")
def export_run(run_id: str, b: Export, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Fige l'enregistrement dans un fichier portable (versionnable) : il survit à la remise à zéro de la base."""
    if not SLUG.match(b.slug):
        raise NotFound("invalid recording name")
    run, a, z = _window(ctx, run_id, None, None)
    events = reconstruct(ctx, a, z or datetime.now(timezone.utc).isoformat())
    doc = {"name": run["name"], "note": run["note"], "from": a, "to": z, "exportedAt": datetime.now(timezone.utc).isoformat(), "events": events}
    path = _dir(ctx) / f"{b.slug}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"file": path.name, "events": len(events)}


@router.get("/replay/recordings")
def list_recordings(p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    out = []
    for f in sorted(_dir(ctx).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"slug": f.stem, "name": d.get("name"), "note": d.get("note"), "from": d.get("from"), "to": d.get("to"), "events": len(d.get("events", []))})
    return {"recordings": out}


@router.get("/replay/recordings/{slug}")
def get_recording(slug: str, p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    path = _dir(ctx) / f"{slug}.json"
    if not SLUG.match(slug) or not path.exists():
        raise NotFound("recording not found")
    return json.loads(path.read_text(encoding="utf-8"))
