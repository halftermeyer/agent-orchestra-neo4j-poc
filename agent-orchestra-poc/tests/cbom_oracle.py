"""Pure-Python reference ("oracle") of the CBOM resolution queries 5.1 to 5.6
of the Neo4j field-industry-use-cases page (configurable-bom).

Graph: nodes = {id: {"labels": {...}, **props}}, edges = [(start, type, end, props)].
Variant links are kept in a dict {(source, rel_type, target): qty} (RESOLVED_LINK).
Used by tests/test_cbom.py as the reference the frozen Cypher queries (queries/kg*/cbom_*.cypher) must match.
Known gap: an option without the constrained property is dropped by Cypher for a deny_list (null IN list is null)
but kept here; every option of the PoC carries `id`, the property the PoC constraints use.
"""
from collections import defaultdict


def _violates(cons_list, group, option):
    """5.1 predicate: does the option y violate a constraint on the ConfigGroup x ?"""
    for cons in cons_list:
        if cons["category"] != group.get("category"):
            continue
        for prop in cons["properties"]:
            val = option.get(prop["name"])
            al, dl = prop.get("allow_list"), prop.get("deny_list")
            if al is not None and val not in al:      # null IN list is null -> path dropped too
                return True
            if dl is not None and val in dl:
                return True
    return False


def resolve(nodes, edges, product_id, constraints):
    """5.1: all paths Product -> Part avoiding forbidden options; union of their edges."""
    out = defaultdict(list)
    for s, t, e, p in edges:
        out[s].append((t, e, p))
    links = {}

    def walk(x, trail):
        used = {(s, t, e) for (s, t, e, q) in trail}
        if "Part" in nodes[x]["labels"]:
            for (s, t, e, q) in trail:
                links[(s, t, e)] = q
            return
        for t, e, p in out[x]:
            if (x, t, e) in used:          # trail semantics: a relationship at most once per path
                continue
            if "ConfigGroup" in nodes[x]["labels"] and _violates(constraints, nodes[x], nodes[e]):
                continue
            walk(e, trail + [(x, t, e, p.get("qty"))])

    walk(product_id, [])
    return links


def _children(links):
    ch = defaultdict(list)
    for (s, t, e) in links:
        ch[s].append(e)
    return ch


def _leaf_sums(links, nodes, start):
    """NOTE: a leaf without cost/weight counts 0 here; Cypher yields null. Keep cost/weight on every leaf.
    sum of cost/weight over leaves below `start`, qty multiplied along the path (start excluded)."""
    ch = _children(links)
    cost = weight = 0.0

    def go(x, times):
        nonlocal cost, weight
        if not ch[x]:
            cost += nodes[x].get("cost", 0.0) * times
            weight += nodes[x].get("weight", 0.0) * times
            return
        for (s, t, e), q in links.items():
            if s == x:
                go(e, times * (1 if q is None else q))
    go(start, 1)
    return cost, weight


def prune(nodes, links, scoring, iterations=10):
    """5.3: bottom-up, keep the best-scoring option of every undecided ConfigGroup."""
    for _ in range(iterations):
        ch = _children(links)

        def undecided(x):
            return "ConfigGroup" in nodes[x]["labels"] and len(ch[x]) > 1

        def reach(x, seen=None):
            seen = seen or set()
            for y in ch[x]:
                if y not in seen:
                    seen.add(y)
                    reach(y, seen)
            return seen
        todo = [x for x in nodes if undecided(x) and not any(undecided(y) for y in reach(x))]
        for cf in todo:
            scored = []
            for (s, t, e) in [k for k in links if k[0] == cf]:
                c, w = _leaf_sums(links, nodes, e)
                vals = {"cost": c, "weight": w}
                scored.append((sum(vals[f["field"]] * f["factor"] for f in scoring), (s, t, e)))
            scored.sort(key=lambda z: (-z[0], z[1][2]))  # tie-break on option id, mirror in Cypher
            for _, k in scored[1:]:
                del links[k]
    return links


def gc(nodes, links, product_id):
    """5.4: drop links whose source is no longer reachable from the Product."""
    ch = _children(links)
    ok, stack = {product_id}, [product_id]
    while stack:
        for y in ch[stack.pop()]:
            if y not in ok:
                ok.add(y)
                stack.append(y)
    for k in [k for k in links if k[0] not in ok]:
        del links[k]
    return links


def totals(nodes, links, product_id):
    """5.5: weight/cost of the resolved BOM."""
    c, w = _leaf_sums(links, nodes, product_id)
    return {"weight": round(w, 6), "cost": round(c, 6)}


def unsatisfied(nodes, edges, links, product_id):
    """5.6: (x, y) with x reachable from Product, x REQUIRES ConfigGroup y, no resolved link x->y."""
    ch = _children(links)
    ok, stack = {product_id}, [product_id]
    while stack:
        for y in ch[stack.pop()]:
            if y not in ok:
                ok.add(y)
                stack.append(y)
    res = set()
    for s, t, e, p in edges:
        if t == "REQUIRES" and s in ok and "ConfigGroup" in nodes[e]["labels"] \
                and not any(k[0] == s and k[2] == e for k in links):
            res.add((s, e))
    return sorted(res)


def run(nodes, edges, product_id, params):
    links = resolve(nodes, edges, product_id, params["constraints"])
    unpruned = dict(links)
    links = gc(nodes, prune(nodes, links, params["scoring"]), product_id)
    return {"unpruned": unpruned, "links": links, "totals": totals(nodes, links, product_id),
            "unsatisfied": unsatisfied(nodes, edges, links, product_id)}
