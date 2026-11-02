import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_agent, require_service
from orchestra.gateway.errors import Forbidden, NotFound, Conflict
from orchestra.gateway.routes.core import Strict, load_session
from orchestra.gateway.store import to_json

router = APIRouter()


def compute_scope(r, agent_id: str) -> dict[str, datetime]:
    """Un seul chemin de code pour calculer le périmètre de lecture (ReBAC)."""
    scopes = r.one("scope", agentId=agent_id)["scopes"]
    return {s["id"]: s["asOf"].to_native() for s in scopes}


@router.get("/scope")
def scope(p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    sc = ctx.store.read(lambda r: compute_scope(r, p.id))
    return {"scopes": [{"id": k, "asOf": v.isoformat()} for k, v in sorted(sc.items())]}


class Ref(Strict):
    db: str
    key: str
    label: str = Field(max_length=200)


class NewFact(Strict):
    sessionId: str
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0, le=1)
    validFrom: datetime | None = None
    about: list[Ref] = Field(default_factory=list, max_length=20)
    derivedFrom: list[str] = Field(default_factory=list, max_length=20)


def _embed(ctx, text: str) -> list[float]:
    v = ctx.llm().embed([text], ctx.settings.embed_dim)[0]
    if len(v) != ctx.settings.embed_dim:
        raise Conflict(f"unexpected embedding dimension: {len(v)}")
    return v


def _check_about_and_sources(ctx, p, about, derived_from):
    def tx(r):
        if about:
            dbs = sorted({a.db for a in about})
            ok = {k["dbName"] for k in r.all("kg_authorize", agentId=p.id, kgIds=dbs)}
            if set(dbs) - ok:
                raise Forbidden(f"no right on graph(s): {sorted(set(dbs) - ok)}")
        if derived_from:
            scope_ = compute_scope(r, p.id)
            vis = {x["id"] for x in r.all("facts_in_scope", ids=derived_from,
                                           scopes=[{"id": k, "asOf": v} for k, v in scope_.items()])}
            if set(derived_from) - vis:
                raise Forbidden("derivedFrom: facts outside your read scope")
    ctx.store.read(tx)


@router.post("/facts", status_code=201)
def remember(b: NewFact, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    s = load_session(ctx, p, b.sessionId)
    _check_about_and_sources(ctx, p, b.about, b.derivedFrom)
    emb = _embed(ctx, b.statement)
    fid = uuid.uuid4().hex
    row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, lambda r: r.one(
        "fact_create", agentId=p.id, sessionId=b.sessionId, factId=fid, statement=b.statement, embedding=emb,
        confidence=b.confidence, validFrom=b.validFrom.isoformat() if b.validFrom else None,
        about=[a.model_dump() for a in b.about], derivedFrom=b.derivedFrom))
    if row is None:
        raise NotFound("memory or session not found")
    return to_json({"id": row["id"], "memoryId": row["memoryId"], "validFrom": row["validFrom"]})


class Revise(Strict):
    sessionId: str
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.8, ge=0, le=1)


@router.post("/facts/{fact_id}/revise", status_code=201)
def revise(fact_id: str, b: Revise, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """On révise, on n'écrase pas : l'ancien fait est fermé (validTo), le nouveau le remplace (SUPERSEDES)."""
    s = load_session(ctx, p, b.sessionId)
    emb = _embed(ctx, b.statement)
    new_id = uuid.uuid4().hex
    row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, lambda r: r.one(
        "fact_revise", agentId=p.id, sessionId=b.sessionId, oldId=fact_id, factId=new_id, statement=b.statement,
        embedding=emb, confidence=b.confidence))
    if row is None:
        raise NotFound("fact not found in your memory, or already closed")
    return to_json(row)


class Recall(Strict):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)
    asOf: datetime | None = None
    memoryIds: list[str] | None = None


@router.post("/recall")
def recall(b: Recall, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    sc = ctx.store.read(lambda r: compute_scope(r, p.id))
    if b.memoryIds is not None:
        sc = {k: v for k, v in sc.items() if k in set(b.memoryIds)}
    if b.asOf:
        cap = b.asOf if b.asOf.tzinfo else b.asOf.replace(tzinfo=timezone.utc)
        sc = {k: min(v, cap) for k, v in sc.items()}
    if not sc:
        return {"facts": []}
    emb = ctx.llm().embed([b.query], ctx.settings.embed_dim)[0]
    rows = ctx.store.read(lambda r: r.all(
        "recall_search", embedding=emb, memoryIds=list(sc), scopes=[{"id": k, "asOf": v} for k, v in sc.items()],
        candidates=b.k * ctx.settings.recall_candidate_factor, k=b.k))
    ctx.log_access(p.id, "recall", True, sorted({x["memoryId"] for x in rows}), detail=f"k={b.k}")
    return {"facts": to_json(rows)}
