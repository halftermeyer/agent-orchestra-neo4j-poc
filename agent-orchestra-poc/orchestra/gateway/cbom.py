"""Change impact on the configurable BOM (CBOM), computed by the gateway, never by an LLM.

Resolution = queries 5.1 to 5.6 of the configurable-bom page (field-industry-use-cases), frozen in
queries/kg_write/cbom_*.cypher and queries/kg/cbom_*.cypher. The released configuration is the `baseline` variant
(every ConfigGroup pinned to the part mounted at its position); `what-if` pins the proposed replacement instead.
Both variants are scratch: resolved, measured and deleted inside ONE KG transaction, so nothing is committed
(no RESOLVED_LINK left behind, no CDC event).
"""
import uuid

SCORING = [{"field": "cost", "factor": -1000}, {"field": "weight", "factor": -1}]   # the page's scoring strategy
MAX_UNSATISFIED = 10


def constraints(selection: list[dict], swap: tuple[str, str] | None = None) -> list[dict]:
    """One allow_list constraint per ConfigGroup (category = group), on the `id` of the options."""
    out = []
    for g in selection:
        allow = [swap[1] if swap and x == swap[0] else x for x in g["selected"]]
        out.append({"category": g["category"], "properties": [{"name": "id", "allow_list": allow}]})
    return out


def resolve_variant(r, product_id: str, id_variant: str, cons: list[dict], scoring=SCORING, keep: bool = False) -> dict:
    """5.1 resolve -> 5.3 prune -> 5.4 gc -> 5.5 totals -> 5.6 unsatisfied, on a Runner (one transaction)."""
    p = {"id_variant": id_variant}
    r.one("kg_write/cbom_resolve", product_id=product_id, constraints=cons, **p)
    r.one("kg_write/cbom_prune", scoring=scoring, **p)
    r.one("kg_write/cbom_gc", **p)
    tot = r.one("kg/cbom_totals", **p)
    uns = r.all("kg/cbom_unsatisfied", **p)
    links = r.all("kg/cbom_resolved", **p)
    if not keep:
        r.one("kg_write/cbom_delete_variant", **p)
    return {"cost": tot["cost"], "weight": tot["weight"], "unsatisfied": [{"source": u["source"], "group": u["group"]} for u in uns],
            "links": links}


def _measure(v: dict) -> dict:
    return {"cost": round(v["cost"] or 0.0, 2), "weight": round(v["weight"] or 0.0, 3), "unsatisfied": len(v["unsatisfied"])}


def _per_product(links: list[dict]) -> dict[str, float]:
    """Quantity of every resolved node per product (product of qty along the resolved paths, summed)."""
    incoming: dict[str, list[tuple[str, float]]] = {}
    for x in links:
        incoming.setdefault(x["target"], []).append((x["source"], 1 if x["qty"] is None else x["qty"]))
    memo: dict[str, float] = {}

    def times(n):
        if n not in memo:
            memo[n] = sum(times(s) * q for s, q in incoming[n]) if n in incoming else 1
        return memo[n]
    return {n: times(n) for n in {x["target"] for x in links} | {x["source"] for x in links}}


def _compare(r, part_id: str, replacement_id: str, tag: str):
    """Baseline and what-if variants of a replacement. Returns (impact, baseline, what_if) on a Runner."""
    sel = r.all("kg/cbom_selection")
    if not sel:
        return {"available": False, "reason": "no CBOM overlay (Product / ConfigGroup) in this knowledge graph"}, None, None
    groups = [g["group"] for g in sel if part_id in g["selected"]]
    if not groups:
        return {"available": False, "reason": f"{part_id} is not mounted at a configurable position of the CBOM"}, None, None
    if part_id == replacement_id:
        return {"available": False, "reason": "the replacement is the part itself"}, None, None
    product = sel[0]["productId"]
    base = resolve_variant(r, product, f"baseline:{tag}", constraints(sel))
    what = resolve_variant(r, product, f"what-if:{tag}", constraints(sel, (part_id, replacement_id)))
    new_uns = [u for u in what["unsatisfied"] if u not in base["unsatisfied"]]
    req = {x["target"]: x for x in base["links"] if x["relType"] == "REQUIRES" and x["target"] in groups}
    times = _per_product(base["links"])
    info = {n["id"]: n for n in r.all("kg/cbom_nodes", ids=[part_id, replacement_id] + [x["source"] for x in req.values()])}
    part = lambda i: {"id": i, "name": info.get(i, {}).get("name"), "cost": info.get(i, {}).get("cost"), "weight": info.get(i, {}).get("weight")}
    positions = [{"group": g, "parent": req[g]["source"], "parentName": info.get(req[g]["source"], {}).get("name"), "qty": req[g]["qty"],
                  "perProduct": times.get(req[g]["source"], 1) * (req[g]["qty"] or 1)} for g in groups if g in req]
    out = {"available": True, "partId": part_id, "replacementId": replacement_id,
           "parts": {"old": part(part_id), "new": part(replacement_id)}, "positions": positions[:MAX_UNSATISFIED],
           "baseline": _measure(base), "whatIf": _measure(what),
           "costDelta": round((what["cost"] or 0.0) - (base["cost"] or 0.0), 2),
           "weightDelta": round((what["weight"] or 0.0) - (base["weight"] or 0.0), 3),
           "unsatisfied": new_uns[:MAX_UNSATISFIED], "complete": not what["unsatisfied"],
           "method": "CBOM 150% resolution (field-industry-use-cases 5.1-5.6), baseline vs what-if"}
    return out, base, what


def impact(store, db: str, meta: dict, part_id: str, replacement_id: str) -> dict:
    """Baseline vs what-if of replacing `part_id` by `replacement_id` everywhere it is mounted (like launch_modification)."""
    tag = uuid.uuid4().hex[:12]
    return store.write_kg(db, meta, lambda r: _compare(r, part_id, replacement_id, tag)[0])


def graph_slice(store, db: str, meta: dict, part_id: str, replacement_id: str) -> dict:
    """The part of the CBOM a replacement touches, for display: the path from the Product to every position of the
    part, its ConfigGroups with all their options (the 150% view), and which links each variant resolved."""
    tag = uuid.uuid4().hex[:12]

    def work(r):
        imp, base, what = _compare(r, part_id, replacement_id, tag)
        if not imp["available"]:
            return {"impact": imp, "nodes": [], "rels": []}
        key = lambda x: (x["source"], x["target"])
        in_base, in_what = {key(x): x for x in base["links"]}, {key(x): x for x in what["links"]}
        parent_of = {}
        for x in base["links"]:
            parent_of.setdefault(x["target"], []).append(x)
        edges: dict[tuple, dict] = {}
        nodes = {part_id, replacement_id}
        stack = [p["parent"] for p in imp["positions"]]
        while stack:                                   # up to the Product along the baseline variant
            n = stack.pop()
            nodes.add(n)
            for x in parent_of.get(n, []):
                if key(x) not in edges:
                    edges[key(x)] = x
                    stack.append(x["source"])
        groups = [p["group"] for p in imp["positions"]]
        for p in imp["positions"]:
            edges[(p["parent"], p["group"])] = in_base[(p["parent"], p["group"])]
        for o in r.all("kg/cbom_group_options", groups=groups):
            edges.setdefault((o["group"], o["option"]), {"source": o["group"], "target": o["option"], "relType": "HAS_OPTION", "qty": None})
            nodes.add(o["option"])
        nodes |= set(groups)
        rels = []
        for k, x in edges.items():
            variant = "both" if k in in_base and k in in_what else "baseline" if k in in_base else "whatif" if k in in_what else "option"
            rels.append({"id": f"{k[0]}>{k[1]}", "from": k[0], "to": k[1], "type": x["relType"], "qty": x["qty"], "variant": variant})
        def role(n):
            if n["id"] in (part_id, replacement_id):
                return "old" if n["id"] == part_id else "new"
            return next((r_ for l, r_ in (("Product", "product"), ("ConfigGroup", "group"), ("Assembly", "assembly")) if l in n["labels"]), "option")
        out_nodes = [{**n, "role": role(n)} for n in r.all("kg/cbom_nodes", ids=sorted(nodes))]
        return {"impact": imp, "nodes": out_nodes, "rels": rels}
    return store.write_kg(db, meta, work)
