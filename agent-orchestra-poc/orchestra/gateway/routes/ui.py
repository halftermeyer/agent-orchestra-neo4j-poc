"""UI support: demo login, chat, approvals, topology, scene state,
agent card, rights (with paths), KG neighborhood, timeline. Read-only, except login."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends

from orchestra.gateway.auth import Principal, get_ctx, make_token, principal, require_person
from orchestra.gateway.errors import Forbidden, NotFound
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.routes.memory import compute_scope
from orchestra.gateway.store import to_json

router = APIRouter()
ADMIN_ENTRY = {"id": "admin", "name": "Administrator", "title": "Settings and supervision", "admin": True}


def require_ui(p: Principal = Depends(principal)) -> Principal:
    if p.kind not in ("user", "admin"):
        raise Forbidden("reserved to UI users")
    return p


def _demo(ctx):
    if not ctx.settings.demo_login:
        raise NotFound("demo login disabled")


@router.get("/demo/users")
def demo_users(ctx=Depends(get_ctx)):
    """User selection for the demo (no password: never enable outside a demo)."""
    _demo(ctx)
    rows = ctx.store.read(lambda r: r.all("demo_users"))
    return {"users": [*rows, ADMIN_ENTRY]}


class Login(Strict):
    userId: str


@router.post("/demo/login")
def demo_login(b: Login, ctx=Depends(get_ctx)):
    _demo(ctx)
    if b.userId == "admin":
        return {"token": make_token(ctx.settings.master_key, "admin", "admin"), "kind": "admin", "id": "admin", "name": ADMIN_ENTRY["name"]}
    row = next((u for u in ctx.store.read(lambda r: r.all("demo_users")) if u["id"] == b.userId), None)
    if row is None:
        raise NotFound("unknown user")
    return {"token": make_token(ctx.settings.master_key, "user", b.userId), "kind": "user", "id": b.userId, "name": row["name"]}


@router.get("/demo/incidents")
def demo_incidents(p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    path = Path(ctx.settings.incidents_file)
    return {"incidents": json.loads(path.read_text(encoding="utf-8")) if path.exists() else []}


def _msg(row: dict) -> dict:
    row["payload"] = json.loads(row.pop("payloadJson")) if row.get("payloadJson") else None
    return row


@router.get("/chat/messages")
def chat_messages(limit: int = 100, p: Principal = Depends(require_person), ctx=Depends(get_ctx)):
    """The logged-in person's inbox (and what they sent): they only see their own."""
    rows = ctx.store.read(lambda r: r.all("chat_messages", agentId=p.id, limit=max(1, min(limit, 300))))
    return {"messages": to_json([_msg(x) for x in reversed(rows)])}


@router.get("/approvals")
def pending_approvals(p: Principal = Depends(require_person), ctx=Depends(get_ctx)):
    rows = ctx.store.read(lambda r: r.all("approvals_pending", agentId=p.id))
    for x in rows:
        x["args"] = json.loads(x["args"]) if x.get("args") else {}
    return {"approvals": to_json(rows)}


@router.get("/graph/topology")
def topology(p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    return to_json(ctx.store.read(lambda r: r.one("topology")))


@router.get("/graph/state")
def graph_state(p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    return {"agents": to_json(ctx.store.read(lambda r: r.all("graph_state")))}


@router.get("/graph/agent/{agent_id}")
def agent_card(agent_id: str, p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    row = ctx.store.read(lambda r: r.one("agent_card", agentId=agent_id))
    if row is None:
        raise NotFound("agent not found")
    return to_json(row)


@router.get("/graph/rights/{agent_id}")
def rights(agent_id: str, p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    """What an agent can read, and via which path: supervision*, then a terminal relationship (whitelist)."""
    rows = ctx.store.read(lambda r: r.all("rights_paths", agentId=agent_id))
    best: dict[str, dict] = {}
    for x in rows:
        nodes = x["chain"] + x["via"] + [x["memoryId"]]
        rels = ["SUPERVISES"] * x["hops"] + x["rels"]
        cur = best.get(x["memoryId"])
        if cur is None or len(nodes) < len(cur["nodes"]):
            best[x["memoryId"]] = {"memoryId": x["memoryId"], "ownerId": x["ownerId"], "kind": x["kind"], "nodes": nodes, "rels": rels,
                                   "asOf": x["asOf"]}
        elif len(nodes) == len(cur["nodes"]) and x["asOf"] > cur["asOf"]:
            cur["asOf"] = x["asOf"]
    return {"agentId": agent_id, "memories": to_json(sorted(best.values(), key=lambda m: (len(m["nodes"]), m["memoryId"])))}


@router.get("/graph/kg/{kg_id}/neighborhood")
def kg_neighborhood(kg_id: str, key: str, p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    """Neighborhood of a KG entity. A person must have rights on the KG (CAN_QUERY), as for any KG access."""
    template = {"produit": "kg/graph_part", "projet": "kg/graph_task"}.get(kg_id)
    if template is None:
        raise NotFound("unknown graph")
    auth = ctx.store.read(lambda r: r.all("kg_authorize", agentId=p.id, kgIds=[kg_id]))
    if not p.is_admin and not auth:
        raise Forbidden("no right on this knowledge graph (CAN_QUERY)")
    db = auth[0]["dbName"] if auth else next(k["dbName"] for k in ctx.store.read(lambda r: r.one("topology"))["kgs"] if k["id"] == kg_id)
    rows = ctx.store.run_in(db, template, key=key)
    nodes: dict[str, dict] = {}
    rels = []
    for x in rows:
        for side in ("s", "t"):
            nodes.setdefault(x[f"{side}id"], {"id": x[f"{side}id"], "name": x[f"{side}name"], "labels": [l for l in x[f"{side}labels"] if l != "Entity"],
                                              "retired": bool(x[f"{side}retired"])})
        rels.append({"id": f"{x['sid']}-{x['type']}-{x['tid']}", "from": x["sid"], "to": x["tid"], "type": x["type"]})
    return {"kg": kg_id, "key": key, "nodes": list(nodes.values()), "rels": list({r["id"]: r for r in rels}.values())}


@router.get("/timeline")
def timeline(hours: int = 24, p: Principal = Depends(require_ui), ctx=Depends(get_ctx)):
    """Timeline: routines (past and upcoming), tool calls, votes, commitments."""
    h = max(1, min(hours, 168))

    def q(r):
        return {k: r.all(f"timeline_{k}", hours=h) for k in ("toolcalls", "votes", "routines", "commitments")} | {"next": r.all("timeline_next_runs")}
    d = ctx.store.read(q)
    items = []
    for x in d["toolcalls"]:
        items.append({"t": x["at"], "end": x["endedAt"], "kind": "tool", "actor": x["actor"], "label": x["tool"], "status": x["status"]})
    for x in d["votes"]:
        items.append({"t": x["at"], "kind": "vote", "actor": x["actor"], "label": x["decision"], "status": x["approvalStatus"], "ref": x["approvalId"]})
    for x in d["routines"]:
        items.append({"t": x["at"], "kind": "routine", "actor": x["actor"], "label": x["routine"].removeprefix("routine:"), "status": "fired"})
    for x in d["commitments"]:
        items.append({"t": x["at"], "end": x["dueAt"], "kind": "commitment", "actor": x["actor"], "label": x["description"], "status": x["status"],
                      "target": x["toAgent"]})
    for x in d["next"]:
        items.append({"t": x["at"], "kind": "routine-next", "actor": x["actor"], "label": x["routine"], "status": "scheduled"})
    items = to_json(items)
    items.sort(key=lambda i: i["t"])
    return {"items": items}
