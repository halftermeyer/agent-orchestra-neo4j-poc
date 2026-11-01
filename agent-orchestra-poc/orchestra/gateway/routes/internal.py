"""Endpoints du consommateur CDC (jeton `sys`). Toute écriture passe par ici : une seule porte d'entrée vers le graphe."""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from neo4j.exceptions import ConstraintError
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_sys
from orchestra.gateway.errors import BudgetExhausted, Conflict, Forbidden, NotFound
from orchestra.gateway.routes.core import PERFORMATIVES, Strict
from orchestra.gateway.store import to_json

router = APIRouter(prefix="/internal")


@router.get("/inbox/{inbox_id}/owners")
def inbox_owners(inbox_id: str, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("inbox_owners", inboxId=inbox_id))
    if not row["exists"]:
        raise NotFound("inbox introuvable")
    return row


@router.get("/messages/{message_id}")
def message(message_id: str, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("message_full", messageId=message_id))
    if row is None:
        raise NotFound("message introuvable")
    row["payload"] = json.loads(row.pop("payloadJson")) if row.get("payloadJson") else None
    return to_json(row)


@router.get("/topics/{topic_id}/routines")
def topic_routines(topic_id: str, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    return {"routines": ctx.store.read(lambda r: r.all("topic_routines", topicId=topic_id))}


@router.get("/routines/due")
def routines_due(now: datetime, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    return {"routines": to_json(ctx.store.read(lambda r: r.all("routines_due", now=now.isoformat())))}


class Advance(Strict):
    nextRunAt: datetime | None = None
    fired: datetime | None = None
    skipped: datetime | None = None
    error: str | None = Field(default=None, max_length=500)
    disable: bool = False


@router.post("/routines/{routine_id}/advance")
def advance(routine_id: str, b: Advance, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    iso = lambda d: d.isoformat() if d else None
    row = ctx.store.write({"agentId": f"sys:{p.id}", "chainId": "none"}, lambda r: r.one(
        "routine_advance", id=routine_id, nextRunAt=iso(b.nextRunAt), fired=iso(b.fired), skipped=iso(b.skipped),
        error=b.error, disable=b.disable))
    if row is None:
        raise NotFound("routine introuvable")
    return row


class Deliver(Strict):
    id: str
    sender: str = Field(alias="from")
    actingAgent: str
    inbox: str
    performative: PERFORMATIVES = "inform"
    body: str = Field(max_length=20000)
    payload: dict | None = None
    chainId: str | None = None
    aboutEvent: str | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}


@router.post("/deliver")
def deliver(b: Deliver, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    """Dépose un message système (routine, topic, pont) dans une inbox, au nom d'un agent.
    Contrôles : CAN_SEND_TO (ou inbox propre) vérifié à chaque déclenchement, quarantaine, budget de chaîne."""
    st = ctx.settings
    auth = ctx.store.read(lambda r: r.one("deliver_authorize", actingAgent=b.actingAgent, inbox=b.inbox))
    if auth is None:
        raise NotFound("agent logiciel ou inbox introuvable")
    if auth["quarantined"]:
        raise Forbidden("agent en quarantaine")
    if not auth["ok"]:
        raise Forbidden(f"{b.actingAgent} n'a pas le droit d'écrire dans {b.inbox} (CAN_SEND_TO)")
    chain_id = b.chainId or b.id

    def tx(r):
        if r.one("message_get", messageId=b.id):
            return {"duplicate": True}
        ch = r.one("chain_charge_messages", chainId=chain_id, agentId=b.actingAgent, n=1,
                   defaultBudget=st.default_budget, defaultTokenBudget=st.default_token_budget)
        if not ch["ok"]:
            return {"refused": ch}
        row = r.one("message_create_system", messageId=b.id, **{"from": b.sender}, actingAgent=b.actingAgent,
                    inbox=b.inbox, performative=b.performative, conversationId=chain_id, chainId=chain_id,
                    body=b.body, payloadJson=json.dumps(b.payload) if b.payload is not None else None,
                    aboutEvent=b.aboutEvent)
        return {"createdAt": row["createdAt"]}
    try:
        out = ctx.store.write({"agentId": b.actingAgent, "chainId": chain_id}, tx)
    except ConstraintError:
        return {"id": b.id, "duplicate": True}
    if "refused" in out:
        ch = out["refused"]
        if ch["prev"] != "active":
            raise Conflict(f"chaîne {ch['prev']}")
        raise BudgetExhausted(f"budget de la chaîne épuisé ({ch['spent']}/{ch['budget']})")
    return to_json({"id": b.id, "chainId": chain_id, "duplicate": out.get("duplicate", False)})


class SyncRef(Strict):
    db: str
    key: str
    op: Literal["update", "delete", "same_as"]
    label: str | None = None
    target: str | None = None


@router.post("/entityrefs/sync")
def sync_ref(b: SyncRef, p: Principal = Depends(require_sys), ctx=Depends(get_ctx)):
    """Cycle de vie des proxys : libellé daté, suppression, redirection (SAME_AS) après fusion."""
    meta = {"agentId": f"sys:{p.id}", "chainId": "none"}
    if b.op == "update":
        row = ctx.store.write(meta, lambda r: r.one("entityref_update", db=b.db, key=b.key, label=b.label))
    elif b.op == "delete":
        row = ctx.store.write(meta, lambda r: r.one("entityref_delete", db=b.db, key=b.key))
    else:
        if not b.target:
            raise Forbidden("same_as exige target")
        row = ctx.store.write(meta, lambda r: r.one("entityref_same_as", db=b.db, key=b.key, target=b.target, label=b.label))
    return {"updated": row is not None}
