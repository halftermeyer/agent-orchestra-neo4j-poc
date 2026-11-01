"""Support des runtimes : lecture de son message et de son fil, catalogue de modèles, engagements,
effet des outils approuvés (launch_modification), signaux de l'auditeur."""
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from neo4j.exceptions import ConstraintError
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_agent, require_service
from orchestra.gateway.errors import Conflict, Forbidden, NotFound
from orchestra.gateway.routes.core import Strict, load_session
from orchestra.gateway.routes.kg import FEDERATED, TEMPLATES
from orchestra.gateway.store import to_json

router = APIRouter()


def _msg(row: dict) -> dict:
    row["payload"] = json.loads(row.pop("payloadJson")) if row.get("payloadJson") else None
    return row


@router.get("/inbox/messages/{message_id}")
def inbox_message(message_id: str, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("inbox_message", agentId=p.id, messageId=message_id))
    if row is None:
        raise NotFound("message absent de votre inbox")
    return to_json(_msg(row))


@router.get("/threads/{chain_id}")
def thread(chain_id: str, limit: int = 20, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    """Ce que *je* sais de la chaîne : messages que j'ai envoyés ou reçus (jamais ceux des autres)."""
    rows = ctx.store.read(lambda r: r.all("thread", agentId=p.id, chainId=chain_id, limit=max(1, min(limit, 50))))
    return {"messages": to_json([_msg(x) for x in reversed(rows)])}


@router.get("/kg/templates")
def kg_templates(p: Principal = Depends(require_agent)):
    return {"templates": [{"kg": kg, "name": n, "params": {k: t[0].__name__ for k, t in spec.items()}} for n, (kg, spec) in TEMPLATES.items()]
            + [{"kg": "federated", "name": n, "params": {k: t[0].__name__ for k, t in spec.items()}} for n, (spec, _, _) in FEDERATED.items()]}


# ---------- engagements ----------
class NewCommitment(Strict):
    sessionId: str
    to: str
    description: str = Field(min_length=1, max_length=500)
    dueInMinutes: int | None = Field(default=None, ge=1, le=129600)
    dueAt: datetime | None = None


@router.post("/commitments", status_code=201)
def create_commitment(b: NewCommitment, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Un engagement est suivi par une minuterie (`once`) : relance du débiteur à l'échéance, par le créancier s'il le peut."""
    s = load_session(ctx, p, b.sessionId)
    now = datetime.now(timezone.utc)
    if b.dueAt:
        due = b.dueAt if b.dueAt.tzinfo else b.dueAt.replace(tzinfo=timezone.utc)
    elif b.dueInMinutes:
        due = now + timedelta(minutes=b.dueInMinutes)
    else:
        raise Forbidden("dueInMinutes ou dueAt requis")
    if due <= now:
        raise Forbidden("l'échéance doit être dans le futur")
    cid = f"cm-{uuid.uuid4().hex[:12]}"

    def tx(r):
        plan = r.one("commitment_plan", agentId=p.id, to=b.to)
        if plan is None or not plan["debtorInbox"]:
            raise NotFound("destinataire de l'engagement introuvable")
        row = r.one("commitment_create", id=cid, agentId=p.id, sessionId=b.sessionId, to=b.to, description=b.description,
                    dueAt=due.isoformat())
        if row is None:
            raise Forbidden("engagement refusé (outil commit non autorisé ou session fermée)")
        owner = b.to if plan["creditorCanRemind"] else p.id
        payload = {"kind": "commitment-due", "commitmentId": cid, "debtor": p.id, "creditor": b.to, "description": b.description,
                   "body": f"Échéance de l'engagement {cid} : {b.description}"}
        r.one("routine_create", agentId=owner, id=f"rt-commit-{cid}", trigger="once", cron=None, tz=None, runAt=due.isoformat(),
              payload=json.dumps(payload), filter=None, misfire="fire", deliverTo=plan["debtorInbox"], listensTo=None)
        return row
    row = ctx.store.write({"agentId": p.id, "chainId": s["chainId"]}, tx)
    return to_json({"id": row["id"], "dueAt": row["dueAt"]})


@router.get("/commitments")
def open_commitments(p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    return {"commitments": to_json(ctx.store.read(lambda r: r.all("commitments_open", agentId=p.id)))}


@router.get("/commitments/{cid}")
def get_commitment(cid: str, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("commitment_get", id=cid, agentId=p.id))
    if row is None:
        raise NotFound("engagement introuvable")
    return to_json(row)


@router.post("/commitments/{cid}/fulfill")
def fulfill_commitment(cid: str, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one("commitment_fulfill", id=cid, agentId=p.id))
    if row is None:
        raise NotFound("engagement ouvert introuvable (ou non à vous)")
    return to_json(row)


# ---------- launch_modification : effet d'un outil irréversible approuvé ----------
class Launch(Strict):
    sessionId: str
    toolCallKey: str


@router.post("/modifications/launch")
def launch_modification(b: Launch, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Exécute exactement ce que le comité a approuvé (arguments figés dans l'appel d'outil), via le conservateur de KG."""
    s = load_session(ctx, p, b.sessionId)
    key = f"{p.id}:{b.toolCallKey}"

    def pre(r):
        return (r.one("launch_context", key=key, agentId=p.id), r.all("kg_authorize", agentId=p.id, kgIds=["produit"]))
    lc, auth = ctx.store.read(pre)
    if lc is None:
        raise NotFound("appel launch_modification introuvable")
    if lc["approvalStatus"] != "approved":
        raise Forbidden(f"validation {lc['approvalStatus']} : aucune exécution")
    if lc["toolCallStatus"] != "working":
        raise Conflict(f"appel déjà {lc['toolCallStatus']}")
    if not auth:
        raise Forbidden("pas de droit sur le KG Produit")
    args = json.loads(lc["args"] or "{}")
    part, repl = args.get("part_id"), args.get("replacement_id")
    if not (part and repl):
        raise Conflict("la validation ne porte pas part_id / replacement_id")
    if ctx.store.kg_driver is None:
        raise Conflict("conservateur de KG non configuré")
    db, change_key = auth[0]["dbName"], f"{lc['approvalId']}"

    def apply(r):
        ex = r.one("kg_write/modification_exists", changeKey=change_key)
        if ex and ex["versionId"]:
            return {"versionId": ex["versionId"], "parents": 0, "replayed": True}
        row = r.one("kg_write/apply_modification", partId=part, replacementId=repl, changeKey=change_key,
                    reason=f"validation {lc['approvalId']}")
        if row is None:
            raise Conflict("pièces introuvables ou déjà retirées")
        return row
    out = ctx.store.write_kg(db, {"agentId": p.id, "chainId": s["chainId"]}, apply)
    # l'appel d'outil est clos par l'agent (tools/calls/{key}/end), avec le message ou le fait produit
    ctx.log_access(p.id, "kg.write", True, [db], detail=f"{out['versionId']}", chain_id=s["chainId"])
    return to_json(out)


# ---------- auditeur : signaux ----------
def _auditor(p: Principal):
    if p.role != "auditor":
        raise Forbidden("réservé à l'auditeur")


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


class Scan(Strict):
    windowMinutes: int = Field(default=15, ge=1, le=1440)
    minMessages: int = Field(default=6, ge=2, le=200)
    budgetRatio: float = Field(default=0.8, gt=0, le=1)
    ratePerMinute: float = Field(default=15, gt=0)
    similarity: float = Field(default=0.92, gt=0, le=1)


@router.post("/audit/scan")
def audit_scan(b: Scan, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Signaux calculés dans le graphe : cycles récents (projection GDS + composantes fortement connexes),
    messages répétés (similarité d'embedding), chaîne qui s'élargit ou dépense trop vite.
    Le LLM n'est consulté par l'auditeur que sur les candidats retournés ici."""
    _auditor(p)
    name = f"audit-{uuid.uuid4().hex[:10]}"
    meta = {"agentId": p.id, "chainId": "audit"}

    def scan(r):
        edges = r.all("audit_chain_edges", agentId=p.id, window=b.windowMinutes)
        sccs = []
        if edges:
            try:
                if r.all("audit_project", agentId=p.id, window=b.windowMinutes, graphName=name):
                    sccs = [set(x["agents"]) for x in r.all("audit_scc", graphName=name)]
            finally:
                try:
                    r.all("audit_drop", graphName=name)
                except Exception:
                    pass
        return edges, sccs
    edges, sccs = ctx.store.write(meta, scan)
    chains: dict[str, dict] = {}
    for e in edges:
        c = chains.setdefault(e["chainId"], {"chainId": e["chainId"], "messages": 0, "agents": set(), "pairs": {}, "budget": e["budget"],
                                             "spent": e["spent"], "tokenBudget": e["tokenBudget"], "tokensSpent": e["tokensSpent"],
                                             "maxTurns": e["maxTurns"], "stopCriterion": e["stopCriterion"], "first": e["first"], "last": e["last"]})
        c["messages"] += e["n"]
        c["agents"] |= {e["from"], e["to"]}
        c["pairs"][(e["from"], e["to"])] = c["pairs"].get((e["from"], e["to"]), 0) + e["n"]
        c["first"], c["last"] = min(c["first"], e["first"]), max(c["last"], e["last"])
    out = []
    for c in chains.values():
        signals = {}
        for comp in sccs:
            n = sum(v for (a, bb), v in c["pairs"].items() if a in comp and bb in comp)
            if n >= b.minMessages:
                signals["cycle"] = {"agents": sorted(comp), "messages": n}
        ratio = (c["spent"] or 0) / c["budget"] if c["budget"] else 0
        if ratio >= b.budgetRatio:
            signals["budget"] = {"spent": c["spent"], "budget": c["budget"], "ratio": round(ratio, 2)}
        minutes = max((c["last"].to_native() - c["first"].to_native()).total_seconds() / 60, 1 / 6)
        rate = c["messages"] / minutes
        if c["messages"] >= b.minMessages and rate >= b.ratePerMinute:
            signals["rate"] = {"perMinute": round(rate, 1), "messages": c["messages"], "agents": len(c["agents"])}
        if not signals:
            continue
        bodies = ctx.store.read(lambda r: r.all("audit_chain_bodies", agentId=p.id, chainId=c["chainId"], limit=8))
        texts = [x["body"] for x in bodies if x["body"]]
        if len(texts) >= 3:
            try:
                vecs = ctx.llm().embed(texts, ctx.settings.embed_dim)
                pairs = [_cos(vecs[i], vecs[j]) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
                mean = sum(pairs) / len(pairs)
                signals["repeated"] = {"meanSimilarity": round(mean, 3), "flag": mean >= b.similarity}
            except Exception:
                signals["repeated"] = {"error": "embedding indisponible"}
        out.append({"chainId": c["chainId"], "messages": c["messages"], "agents": sorted(c["agents"]),
                    "declaredLoop": {"maxTurns": c["maxTurns"], "stopCriterion": c["stopCriterion"]} if c["maxTurns"] or c["stopCriterion"] else None,
                    "signals": signals})
    ctx.log_access(p.id, "audit.scan", True, [x["chainId"] for x in out], detail=f"window={b.windowMinutes}", chain_id="audit")
    return {"candidates": to_json(out)}


@router.get("/audit/chains/{chain_id}/episode")
def audit_episode(chain_id: str, limit: int = 30, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Épisodique des agents audités (messages envoyés), jamais leurs mémoires."""
    _auditor(p)
    rows = ctx.store.read(lambda r: r.all("audit_chain_bodies", agentId=p.id, chainId=chain_id, limit=max(1, min(limit, 60))))
    ctx.log_access(p.id, "audit.episode", True, [chain_id], chain_id="audit")
    return {"messages": to_json(list(reversed(rows)))}
