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


def impact(store, db: str, meta: dict, part_id: str, replacement_id: str) -> dict:
    """Baseline vs what-if of replacing `part_id` by `replacement_id` everywhere it is mounted (like launch_modification)."""
    tag = uuid.uuid4().hex[:12]

    def work(r):
        sel = r.all("kg/cbom_selection")
        if not sel:
            return {"available": False, "reason": "no CBOM overlay (Product / ConfigGroup) in this knowledge graph"}
        groups = [g["group"] for g in sel if part_id in g["selected"]]
        if not groups:
            return {"available": False, "reason": f"{part_id} is not mounted at a configurable position of the CBOM"}
        if part_id == replacement_id:
            return {"available": False, "reason": "the replacement is the part itself"}
        product = sel[0]["productId"]
        base = resolve_variant(r, product, f"baseline:{tag}", constraints(sel))
        what = resolve_variant(r, product, f"what-if:{tag}", constraints(sel, (part_id, replacement_id)))
        new_uns = [u for u in what["unsatisfied"] if u not in base["unsatisfied"]]
        return {"available": True, "partId": part_id, "replacementId": replacement_id, "groups": groups[:MAX_UNSATISFIED],
                "baseline": _measure(base), "whatIf": _measure(what),
                "costDelta": round((what["cost"] or 0.0) - (base["cost"] or 0.0), 2),
                "weightDelta": round((what["weight"] or 0.0) - (base["weight"] or 0.0), 3),
                "unsatisfied": new_uns[:MAX_UNSATISFIED], "complete": not what["unsatisfied"],
                "method": "CBOM 150% resolution (field-industry-use-cases 5.1-5.6), baseline vs what-if"}
    return store.write_kg(db, meta, work)
