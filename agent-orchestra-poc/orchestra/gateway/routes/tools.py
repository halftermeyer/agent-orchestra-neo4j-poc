import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from neo4j.exceptions import ConstraintError
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_agent, require_person, require_service
from orchestra.gateway.errors import Conflict, Forbidden, NotFound
from orchestra.gateway.routes.core import Strict, load_session
from orchestra.gateway.store import to_json

router = APIRouter()


def _key(p: Principal, k: str) -> str:
    return f"{p.id}:{k}"


class StartCall(Strict):
    sessionId: str
    tool: str
    idempotencyKey: str = Field(min_length=1, max_length=200)
    args: dict | None = None


@router.post("/tools/calls", status_code=201)
def start_call(b: StartCall, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    s = load_session(ctx, p, b.sessionId)
    auth = ctx.store.read(lambda r: r.one("tool_authorize", agentId=p.id, tool=b.tool))
    if auth is None:
        raise Forbidden("outil non autorisé (CAN_USE ; le droit ne s'hérite pas)")
    if auth["effect"] == "irreversible":
        raise Forbidden("action irréversible : passer par /approvals")
    key = _key(p, b.idempotencyKey)
    args = json.dumps(b.args)[:4000] if b.args is not None else None
    try:
        row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, lambda r: r.one(
            "toolcall_create", agentId=p.id, tool=b.tool, sessionId=b.sessionId, key=key, args=args))
    except ConstraintError:
        return to_json({**ctx.store.read(lambda r: r.one("toolcall_get", key=key, agentId=p.id)), "replayed": True})
    return to_json(row)


class EndCall(Strict):
    status: Literal["completed", "failed"]
    tokens: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=1000)
    factId: str | None = None
    messageId: str | None = None


@router.post("/tools/calls/{key}/end")
def end_call(key: str, b: EndCall, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    full = _key(p, key)
    cur = ctx.store.read(lambda r: r.one("toolcall_get", key=full, agentId=p.id))
    if cur is None:
        raise NotFound("appel d'outil introuvable")
    if cur["status"] in ("completed", "failed", "canceled"):
        return to_json({**cur, "replayed": True})
    if cur["status"] != "working":
        raise Conflict(f"appel en état {cur['status']}")
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one(
        "toolcall_end", key=full, agentId=p.id, status=b.status, tokens=b.tokens, error=b.error,
        factId=b.factId, messageId=b.messageId))
    return to_json(row)


class RequestApproval(Strict):
    sessionId: str
    tool: str
    idempotencyKey: str = Field(min_length=1, max_length=200)
    electorate: str
    args: dict | None = None


@router.post("/approvals", status_code=201)
def request_approval(b: RequestApproval, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    s = load_session(ctx, p, b.sessionId)
    auth = ctx.store.read(lambda r: r.one("tool_authorize", agentId=p.id, tool=b.tool))
    if auth is None or auth["effect"] != "irreversible":
        raise Forbidden("outil non autorisé ou non soumis à validation")
    m = re.fullmatch(r"(\d+)-of-(\d+)", auth["approval"] or "")
    if not m:
        raise Conflict("politique d'approbation invalide")
    quorum, size = int(m[1]), int(m[2])
    key = _key(p, b.idempotencyKey)
    aid = uuid.uuid4().hex

    def tx(r):
        row = r.one("approval_create", agentId=p.id, tool=b.tool, sessionId=b.sessionId, key=key, electorate=b.electorate,
                    approvalId=aid, quorum=quorum, size=size, args=json.dumps(b.args)[:4000] if b.args else None)
        if row is None:
            raise Forbidden("électorat non autorisé (CAN_SEND_TO) ou session fermée")
        if row["electors"] < size:
            raise Conflict(f"électorat trop petit : {row['electors']} < {size}")
        return row
    try:
        row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, tx)
    except ConstraintError:
        row = ctx.store.read(lambda r: r.one("approval_by_key", key=key, agentId=p.id))
        return to_json({**row, "replayed": True})
    return to_json({"id": row["id"], "status": row["status"], "quorum": quorum, "size": size})


def _can_see(ctx, p, ap) -> bool:
    if p.is_admin or ap["requestedBy"] == p.id:
        return True
    if not p.is_person:
        return False
    el = ctx.store.read(lambda r: r.one("approval_eligibility", personId=p.id, approvalId=ap["id"]))
    return bool(el["member"] or el["delegatorId"])


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    ap = ctx.store.read(lambda r: r.one("approval_get", approvalId=approval_id))
    if ap is None or not _can_see(ctx, p, ap):
        raise NotFound("validation introuvable")
    return to_json(ap)


class Vote(Strict):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/approvals/{approval_id}/votes", status_code=201)
def vote(approval_id: str, b: Vote, p: Principal = Depends(require_person), ctx=Depends(get_ctx)):
    """Seules des personnes votent (un agent logiciel recommande, il ne vote pas)."""
    ap = ctx.store.read(lambda r: r.one("approval_get", approvalId=approval_id))
    if ap is None:
        raise NotFound("validation introuvable")
    el = ctx.store.read(lambda r: r.one("approval_eligibility", personId=p.id, approvalId=approval_id))
    if el["member"]:
        effective, on_behalf = p.id, None
    elif el["delegatorId"]:
        effective, on_behalf = el["delegatorId"], el["delegatorId"]
    else:
        raise Forbidden("vous ne faites pas partie de l'électorat (ni délégué en cours)")
    if ap["status"] != "pending":
        raise Conflict(f"validation déjà {ap['status']}")

    def tx(r):
        v = r.one("approval_vote", approvalId=approval_id, personId=p.id, decision=b.decision, comment=b.comment,
                  effectiveVoter=effective, onBehalfOf=on_behalf)
        if v is None:
            raise Conflict("validation close, ou cette voix a déjà été exprimée")
        return r.one("approval_tally", approvalId=approval_id)
    try:
        out = ctx.store.write({"agentId": p.id, "chainId": ap["chainId"] or "none"}, tx)
    except ConstraintError:
        raise Conflict("vous avez déjà voté") from None
    return to_json(out)
