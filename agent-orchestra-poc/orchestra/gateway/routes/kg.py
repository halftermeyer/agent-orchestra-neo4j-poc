import uuid

from fastapi import APIRouter, Depends

from orchestra.gateway.auth import Principal, get_ctx, require_agent
from orchestra.gateway.errors import Forbidden, NotFound
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.store import to_json

router = APIRouter()

# Query templates: kg -> {template: {param: (type, default)}}. Whitelist; no free-form Cypher.
TEMPLATES = {
    "part_info": ("produit", {"partId": (str, None)}),
    "part_children": ("produit", {"partId": (str, None)}),
    "part_where_used": ("produit", {"partId": (str, None)}),
    "part_tests": ("produit", {"partId": (str, None)}),
    "replacement_candidates": ("produit", {"partId": (str, None), "limit": (int, 5)}),
    "project_graph": ("projet", {}),
    "tasks_for_tests": ("projet", {"testIds": (list, None)}),
}
FEDERATED = {"impact_part": ({"partId": (str, None)}, ["produit", "projet"], "federated_impact_part")}


def _validate(spec: dict, params: dict) -> dict:
    extra = set(params) - set(spec)
    if extra:
        raise Forbidden(f"unknown parameters: {sorted(extra)}")
    out = {}
    for name, (typ, default) in spec.items():
        v = params.get(name, default)
        if v is None or not isinstance(v, typ) or isinstance(v, bool):
            raise Forbidden(f"invalid parameter: {name}")
        if typ is list and not all(isinstance(x, str) for x in v):
            raise Forbidden(f"invalid parameter: {name}")
        if typ is int:
            v = max(1, min(v, 20))
        out[name] = v
    return out


class KgQuery(Strict):
    kg: str
    template: str
    params: dict = {}


@router.post("/kg/query")
def kg_query(b: KgQuery, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    if b.template not in TEMPLATES:
        raise NotFound(f"unknown query template: {b.template}. Available templates: {sorted(TEMPLATES)}")
    kg_id, spec = TEMPLATES[b.template]
    if b.kg != kg_id:
        raise Forbidden(f"the template {b.template} applies to the {kg_id} graph")
    params = _validate(spec, b.params)
    auth = ctx.store.read(lambda r: r.all("kg_authorize", agentId=p.id, kgIds=[kg_id]))
    ctx.log_access(p.id, "kg.query", bool(auth), [kg_id], detail=b.template)
    if not auth:
        raise Forbidden("no right on this knowledge graph (CAN_QUERY)")
    return {"rows": to_json(ctx.store.run_in(auth[0]["dbName"], f"kg/{b.template}", **params))}


class Federated(Strict):
    template: str
    params: dict = {}


@router.post("/kg/federated")
def kg_federated(b: Federated, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    if b.template not in FEDERATED:
        raise NotFound("unknown federated template")
    spec, kgs, qname = FEDERATED[b.template]
    params = _validate(spec, b.params)
    auth = ctx.store.read(lambda r: r.all("kg_authorize", agentId=p.id, kgIds=kgs))
    granted = len({k["id"] for k in auth}) == len(kgs)
    ctx.log_access(p.id, "kg.federated", granted, kgs, detail=b.template)
    if not granted:
        raise Forbidden("a federated query requires a right on every graph it touches")
    return {"rows": to_json(ctx.store.run_in("fed", qname, **params))}


class Resolve(Strict):
    db: str
    key: str


@router.post("/kg/resolve")
def kg_resolve(b: Resolve, p: Principal = Depends(require_agent), ctx=Depends(get_ctx)):
    """No leak through the proxy: the right on the KnowledgeGraph is checked before any EntityRef read."""
    auth = ctx.store.read(lambda r: r.all("kg_authorize", agentId=p.id, kgIds=[b.db]))
    auth = [a for a in auth if a["dbName"] == b.db]
    ctx.log_access(p.id, "kg.resolve", bool(auth), [b.db], detail=b.key)
    if not auth:
        raise Forbidden("no right on this knowledge graph (CAN_QUERY)")
    rows = ctx.store.run_in(b.db, "kg/entity_exists", key=b.key)
    ref = ctx.store.read(lambda r: r.one("entityref_redirect", db=b.db, key=b.key))
    return to_json({**rows[0], "deletedAt": ref["deletedAt"], "redirectTo": ref["redirectTo"]})
