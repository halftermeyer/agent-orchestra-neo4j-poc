import json
import uuid
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from fastapi import APIRouter, Depends
from pydantic import Field

from orchestra import predicate
from orchestra.gateway.auth import Principal, get_ctx, principal, require_agent
from orchestra.gateway.errors import Forbidden, NotFound
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.store import to_json

router = APIRouter()


@router.get("/auth/check")
def auth_check(p: Principal = Depends(principal)):
    """Validation d'un jeton pour les services voisins (WebSocket du consommateur CDC)."""
    return {"kind": p.kind, "id": p.id}


@router.get("/inbox/pending")
def inbox_pending(limit: int = 100, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    """Messages `submitted` de mon inbox : rattrapage d'un runtime qui s'est connecté après le réveil."""
    return {"pending": to_json(ctx.store.read(lambda r: r.all("inbox_pending", agentId=p.id, limit=max(1, min(limit, 500)))))}


class NewRoutine(Strict):
    trigger: Literal["cron", "once", "event"]
    deliverTo: str
    cron: str | None = None
    tz: str = "Europe/Paris"
    runAt: datetime | None = None
    listensTo: str | None = None
    filter: dict | None = None
    payload: dict | None = None
    misfire: Literal["skip", "fire"] | None = None


@router.post("/routines", status_code=201)
def create_routine(b: NewRoutine, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    """CAN_SEND_TO (ou inbox propre) est vérifié ici, puis à chaque déclenchement."""
    try:
        if b.trigger == "cron":
            if not b.cron or not croniter.is_valid(b.cron):
                raise ValueError("expression cron invalide")
            ZoneInfo(b.tz)
        elif b.trigger == "once":
            if b.runAt is None:
                raise ValueError("runAt requis pour une minuterie")
        else:
            if not b.listensTo or b.filter is None:
                raise ValueError("listensTo et filter requis pour un abonnement")
            predicate.validate(b.filter)
    except Exception as e:
        raise Forbidden(str(e)) from None
    chk = ctx.store.read(lambda r: r.one("routine_authorize", agentId=p.id, deliverTo=b.deliverTo, listensTo=b.listensTo))
    if not chk["canDeliver"]:
        raise Forbidden("envoi non autorisé vers cette inbox (CAN_SEND_TO)")
    if not chk["topicOk"]:
        raise NotFound("topic introuvable")
    run_at = None
    if b.runAt:
        run_at = (b.runAt if b.runAt.tzinfo else b.runAt.replace(tzinfo=timezone.utc)).isoformat()
    rid = f"rt-{uuid.uuid4().hex[:12]}"
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one(
        "routine_create", agentId=p.id, id=rid, trigger=b.trigger, cron=b.cron, tz=b.tz if b.trigger == "cron" else None,
        runAt=run_at, payload=json.dumps(b.payload) if b.payload is not None else None,
        filter=json.dumps(b.filter) if b.filter is not None else None,
        misfire=b.misfire or ("fire" if b.trigger == "once" else "skip"), deliverTo=b.deliverTo, listensTo=b.listensTo))
    return to_json(row)


@router.post("/routines/{routine_id}/disable")
def disable_routine(routine_id: str, p: Principal = Depends(principal), ctx=Depends(get_ctx)):
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one(
        "routine_disable", id=routine_id, agentId=p.id, isAdmin=p.is_admin))
    if row is None:
        raise NotFound("routine introuvable ou non possédée")
    return to_json(row)
