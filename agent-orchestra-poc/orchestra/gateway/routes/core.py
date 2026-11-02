import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from neo4j.exceptions import ConstraintError
from pydantic import BaseModel, ConfigDict, Field

from orchestra.gateway.auth import Principal, get_ctx, principal, require_admin, require_agent, require_person, require_service
from orchestra.gateway.errors import BudgetExhausted, Conflict, Forbidden, NotFound
from orchestra.gateway.store import to_json

router = APIRouter()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


PERFORMATIVES = Literal["inform", "request", "query", "agree", "refuse", "propose", "accept-proposal",
                        "reject-proposal", "confirm", "failure", "cancel"]


def load_session(ctx, p: Principal, session_id: str, need_open: bool = True) -> dict:
    s = ctx.store.read(lambda r: r.one("session_get", sessionId=session_id))
    if s is None or s["agentId"] != p.id:
        raise NotFound("session not found")
    if need_open and s["closedAt"] is not None:
        raise Conflict("session closed")
    return s


@router.get("/me")
def me(p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    return to_json(ctx.store.read(lambda r: r.one("me", agentId=p.id)))


# ---------- sessions ----------
class OpenSession(Strict):
    messageId: str


@router.post("/sessions")
def open_session(b: OpenSession, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Idempotent: MERGE on the triggering message (key `<messageId>@<agentId>`)."""
    m = ctx.store.read(lambda r: r.one("message_get", messageId=b.messageId))
    if m is None:
        raise NotFound("message not found")
    meta = {"agentId": p.id, "chainId": m["chainId"] or b.messageId}
    row = ctx.store.write(meta, lambda r: r.one("session_open", agentId=p.id, messageId=b.messageId,
                                               triggerMsgId=f"{b.messageId}@{p.id}"))
    if row is None:
        raise Forbidden("this message is not in this agent's inbox")
    return to_json(row)


class CloseSession(Strict):
    status: Literal["completed", "failed", "canceled", "input-required"] = "completed"


@router.post("/sessions/{session_id}/close")
def close_session(session_id: str, b: CloseSession, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    s = load_session(ctx, p, session_id, need_open=False)
    row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]},
                          lambda r: r.one("session_close", sessionId=session_id, agentId=p.id, status=b.status))
    return to_json(row)


class SetStatus(Strict):
    sessionId: str
    text: str = Field(min_length=1, max_length=280)


@router.post("/status")
def set_status(b: SetStatus, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    s = load_session(ctx, p, b.sessionId)
    row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, lambda r: r.one(
        "status_set", sessionId=b.sessionId, agentId=p.id, id=uuid.uuid4().hex, text=b.text))
    return to_json(row)


# ---------- messages ----------
class AttachMemory(Strict):
    memoryId: str | None = None
    mode: Literal["snapshot", "live"] = "snapshot"
    until: datetime | None = None
    private: bool = False


class SendMessage(Strict):
    to: list[str] = Field(min_length=1, max_length=20)
    performative: PERFORMATIVES
    body: str = Field(max_length=20000)
    sessionId: str | None = None
    conversationId: str | None = None
    chainId: str | None = None
    inReplyTo: str | None = None
    id: str | None = None
    payload: dict | None = None
    attachMemory: AttachMemory | None = None
    derivedFrom: str | None = None


@router.post("/messages", status_code=201)
def send_message(b: SendMessage, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    import json
    st = ctx.settings
    recipients = list(dict.fromkeys(b.to))
    if b.id and p.kind != "svc":
        raise Forbidden("forced id is reserved to services")
    msg_id = b.id or uuid.uuid4().hex

    def pre(r):
        sc = r.one("send_context", agentId=p.id, recipients=recipients)
        sess = r.one("session_get", sessionId=b.sessionId) if b.sessionId else None
        mem = None
        if b.attachMemory:
            mid = b.attachMemory.memoryId or f"mem:{p.id}"
            mem = (mid, (r.one("memory_shareable", agentId=p.id, memoryId=mid) or {}).get("ok", False))
        return sc, sess, mem
    sc, sess, mem = ctx.store.read(pre)

    denied = [x for x in recipients if x not in sc["allowed"]]
    if denied:
        raise Forbidden(f"sending not allowed (CAN_SEND_TO) to: {denied}")
    if not sc["isPerson"] and not sc["hasMandate"]:
        if b.performative != "query" or not set(recipients) <= set(sc["supervisorInboxes"]):
            raise Forbidden("no mandate: only a question (query) to your supervisor is allowed")

    if p.kind == "svc":
        if sess is None or sess["agentId"] != p.id:
            raise Forbidden("an open session is required")
        if sess["closedAt"] is not None:
            raise Conflict("session closed")
        chain_id = sess["chainId"]
        if b.chainId and b.chainId != chain_id:
            raise Forbidden("a session can only write in its own chain")
    else:
        chain_id = b.chainId or uuid.uuid4().hex
    conversation_id = b.conversationId or chain_id

    attach = None
    if b.attachMemory:
        if not mem[1]:
            raise Forbidden("memory sharing not allowed (neither owner nor CAN_SHARE)")
        now = datetime.now(timezone.utc)
        a = b.attachMemory
        if a.mode == "live":
            if a.until is None:
                raise Forbidden("a live share must expire (until)")
            until = a.until if a.until.tzinfo else a.until.replace(tzinfo=timezone.utc)
            if until <= now or until > now + timedelta(days=st.max_live_days):
                raise Forbidden(f"until must be in the future and within {st.max_live_days} days")
        else:
            until = now + timedelta(days=st.share_ttl_days)
        attach = {"memoryId": mem[0], "mode": a.mode, "until": until.isoformat(), "private": a.private}

    def tx(r):
        ex = r.one("message_get", messageId=msg_id)
        if ex:
            if ex["from"] != p.id:
                raise Conflict("message id already in use")
            return {"duplicate": True, "createdAt": ex["createdAt"]}
        ch = r.one("chain_charge_messages", chainId=chain_id, agentId=p.id, n=len(recipients),
                   defaultBudget=st.default_budget, defaultTokenBudget=st.default_token_budget)
        if not ch["ok"]:
            return {"refused": ch}
        session_id = b.sessionId
        if p.kind == "user":
            session_id = r.one("session_open_direct", agentId=p.id, chainId=chain_id,
                               triggerMsgId=f"direct:{msg_id}@{p.id}")["id"]
        row = r.one("message_create", sessionId=session_id, agentId=p.id, chainId=chain_id, messageId=msg_id,
                    performative=b.performative, conversationId=conversation_id, body=b.body, inReplyTo=b.inReplyTo,
                    payloadJson=json.dumps(b.payload) if b.payload is not None else None,
                    recipients=recipients, derivedFrom=b.derivedFrom)
        if attach:
            r.one("message_attach_memory", messageId=msg_id, agentId=p.id, **attach)
        if p.kind == "user":                   # a human's direct session has a single send: close it (otherwise they would stay "busy")
            r.one("session_close", sessionId=session_id, agentId=p.id, status="completed")
        return {"createdAt": row["createdAt"]}

    try:
        out = ctx.store.write({"agentId": p.id, "chainId": chain_id}, tx)
    except ConstraintError:
        raise Conflict("duplicate message") from None
    if "refused" in out:
        ch = out["refused"]
        if ch["prev"] != "active":
            raise Conflict(f"chain {ch['prev']}")
        raise BudgetExhausted(f"chain budget exhausted ({ch['spent']}/{ch['budget']}): chain suspended")
    return to_json({"id": msg_id, "chainId": chain_id, "conversationId": conversation_id, "recipients": recipients,
                    "createdAt": out["createdAt"], "duplicate": out.get("duplicate", False)})


# ---------- chains ----------
class CreateChain(Strict):
    id: str
    budget: int = Field(gt=0, le=100000)
    tokenBudget: int = Field(gt=0, le=100_000_000)
    stopCriterion: str | None = None
    maxTurns: int | None = None


@router.post("/chains", status_code=201)
def create_chain(b: CreateChain, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Intentional loop: declared (stop criterion, maximum turns) and given a budget."""
    return to_json(ctx.store.write({"agentId": p.id, "chainId": b.id}, lambda r: r.one(
        "chain_create", chainId=b.id, by=p.id, budget=b.budget, tokenBudget=b.tokenBudget,
        stopCriterion=b.stopCriterion, maxTurns=b.maxTurns)))


@router.get("/chains/{chain_id}")
def get_chain(chain_id: str, p: Principal = Depends(principal), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("chain_get", chainId=chain_id))
    if row is None:
        raise NotFound("chain not found")
    return to_json(row)


class Reason(Strict):
    reason: str = Field(max_length=500)


@router.post("/chains/{chain_id}/suspend")
def suspend_chain(chain_id: str, b: Reason, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    row = ctx.store.write({"agentId": p.id, "chainId": chain_id}, lambda r: r.one(
        "chain_suspend", agentId=p.id, chainId=chain_id, reason=b.reason))
    if row is None:
        raise Forbidden("reserved to the auditor (suspend_chain tool), on an existing chain")
    return to_json(row)


class Resume(Strict):
    extraBudget: int = Field(default=0, ge=0, le=100000)
    extraTokens: int = Field(default=0, ge=0, le=100_000_000)


@router.post("/chains/{chain_id}/resume")
def resume_chain(chain_id: str, b: Resume, p: Principal = Depends(principal), ctx=Depends(get_ctx)):
    if not (p.is_admin or p.is_person):
        raise Forbidden("resuming a chain is a human decision")
    row = ctx.store.write({"agentId": p.id, "chainId": chain_id}, lambda r: r.one(
        "chain_resume", chainId=chain_id, by=p.id, extraBudget=b.extraBudget, extraTokens=b.extraTokens))
    if row is None:
        raise Conflict("chain does not exist or is not suspended")
    return to_json(row)


class CloseChain(Strict):
    reason: str = Field(default="", max_length=500)


@router.post("/chains/{chain_id}/close")
def close_chain(chain_id: str, b: CloseChain, p: Principal = Depends(principal), ctx=Depends(get_ctx)):
    """Human decision: permanently close a chain (active or suspended). No further sends are accepted."""
    if not (p.is_admin or p.is_person):
        raise Forbidden("closing a chain is a human decision")
    row = ctx.store.write({"agentId": p.id, "chainId": chain_id}, lambda r: r.one("chain_close", chainId=chain_id, by=p.id, reason=b.reason))
    if row is None:
        raise Conflict("chain does not exist or is already closed")
    return to_json(row)


class Quarantine(Strict):
    reason: str = Field(max_length=500)


@router.post("/agents/{target}/quarantine")
def quarantine(target: str, b: Quarantine, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one(
        "quarantine", agentId=p.id, target=target, reason=b.reason))
    if row is None:
        raise Forbidden("reserved to the auditor, on another software agent")
    return to_json(row)


@router.post("/agents/{target}/release")
def release(target: str, p: Principal = Depends(principal), ctx=Depends(get_ctx)):
    if not (p.is_admin or p.is_person):
        raise Forbidden("lifting a quarantine is a human decision")
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one("unquarantine", target=target, by=p.id))
    if row is None:
        raise Conflict("agent not found or not quarantined")
    return to_json(row)
