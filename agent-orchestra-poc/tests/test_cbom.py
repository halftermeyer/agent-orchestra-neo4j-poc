"""CBOM change impact: the frozen Cypher (queries 5.1-5.6 of the configurable-bom page) against the pure-Python oracle,
on the page's bike and on the PoC seed; then the gateway (approval args, evaluate_change, launch)."""
import json

import pytest

from cbom_fixtures import BIKE, bike_oracle_input, load_bike, load_poc, poc_data, poc_oracle_input, poc_selection
from cbom_oracle import run as oracle_run
from conftest import KGTEST, tok
from orchestra.gateway.cbom import SCORING, resolve_variant
from orchestra.gateway.store import Runner
from orchestra.seed import kg_data as K

PAGE = {"loosely-defined": ({"weight": 8.43, "cost": 1045.0}, []),
        "well-defined": ({"weight": 7.68, "cost": 1115.0}, []),
        "over-constrained": ({"weight": 8.13, "cost": 1065.0}, [("A_Frame", "CG_Color")])}


def _cypher_variant(admin, db, product, variant, cons, scoring=SCORING):
    with admin.session(database=db) as s:
        out = s.execute_write(lambda tx: resolve_variant(Runner(tx), product, variant, cons, scoring))
        left = s.run("CYPHER 25 MATCH ()-[r:RESOLVED_LINK]->() RETURN count(r) AS n").single()["n"]
    assert left == 0, "scratch variant left RESOLVED_LINKs behind"
    return out


def _links(v):
    return {(x["source"], x["relType"], x["target"], x["qty"]) for x in v["links"]}


def _oracle_links(o):
    return {(s, t, e, q) for (s, t, e), q in o["links"].items()}


def _same(cy, orc):
    assert _links(cy) == _oracle_links(orc)
    assert cy["cost"] == pytest.approx(orc["totals"]["cost"]) and cy["weight"] == pytest.approx(orc["totals"]["weight"])
    assert sorted((u["source"], u["group"]) for u in cy["unsatisfied"]) == orc["unsatisfied"]


# ---------- the page's bike ----------
@pytest.fixture(scope="module")
def bike(admin, kgtest):
    load_bike(admin, kgtest)
    yield kgtest
    with admin.session(database=kgtest) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()


@pytest.mark.parametrize("name", list(PAGE))
def test_bike_matches_the_page_and_the_oracle(admin, bike, name):
    params = BIKE["params"][name]
    cy = _cypher_variant(admin, bike, "MB1", params["id_variant"], params["constraints"], params["scoring"])
    nodes, edges = bike_oracle_input()
    orc = oracle_run(nodes, edges, "MB1", params)
    _same(cy, orc)
    totals, unsatisfied = PAGE[name]
    assert {"weight": round(cy["weight"], 6), "cost": cy["cost"]} == totals
    assert [(u["source"], u["group"]) for u in cy["unsatisfied"]] == unsatisfied


# ---------- the PoC seed ----------
@pytest.fixture(scope="module")
def poc(admin, kgtest):
    produit, cbom = load_poc(admin, kgtest)
    yield produit, cbom
    with admin.session(database=kgtest) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()


def _poc_case(admin, poc, swap=None, constraints=None):
    produit, cbom = poc
    cons = poc_selection(cbom, swap) if constraints is None else constraints
    cy = _cypher_variant(admin, KGTEST, cbom["product"], "t", cons)
    nodes, edges = poc_oracle_input(produit, cbom)
    orc = oracle_run(nodes, edges, cbom["product"], {"constraints": cons, "scoring": SCORING})
    _same(cy, orc)
    return cy


def _rollup(produit, cost_of=None):
    """Plain released BOM roll-up over CONTAINS (independent of the CBOM): sum of leaf cost x product of qty."""
    parts = {p["id"]: p for p in produit["parts"]}
    kids = {}
    for c in produit["contains"]:
        kids.setdefault(c["from"], []).append((c["to"], c["qty"]))
    cost_of = cost_of or (lambda x: parts[x].get("cost", 0.0))

    def go(x, times):
        return cost_of(x) * times if x not in kids else sum(go(y, times * q) for y, q in kids[x])
    return go(produit["parts"][0]["id"], 1)


def _replacement(produit, part, same_family=True):
    parts = {p["id"]: p for p in produit["parts"]}
    _, _, _, candidates = K._bom_index(produit)
    if same_family:
        return candidates(part)[1]
    return next(p["id"] for p in produit["parts"] if p["level"] == 3 and p["family"] != parts[part]["family"])


def test_poc_baseline_matches_the_oracle_and_the_plain_rollup(admin, poc):
    produit, _ = poc
    cy = _poc_case(admin, poc)
    assert cy["unsatisfied"] == []
    assert cy["cost"] == pytest.approx(_rollup(produit))        # flagged CONTAINS are not counted twice


@pytest.mark.parametrize("which", ["loop", "unshared"])
def test_poc_what_if_same_family_matches_the_oracle(admin, poc, which):
    produit, cbom = poc
    part = K.loop_parts(produit)[0] if which == "loop" else \
        next(c["to"] for c in cbom["configurable"] if sum(x["to"] == c["to"] for x in cbom["configurable"]) == 1)
    repl = _replacement(produit, part)
    base, what = _poc_case(admin, poc), _poc_case(admin, poc, swap=(part, repl))
    assert what["unsatisfied"] == []
    parts = {p["id"]: p for p in produit["parts"]}
    expected = _rollup(produit, lambda x: parts[repl]["cost"] if x == part else parts[x].get("cost", 0.0))
    assert what["cost"] == pytest.approx(expected) and what["cost"] != pytest.approx(base["cost"])


def test_poc_what_if_outside_the_options_leaves_requirements_unsatisfied(admin, poc):
    produit, cbom = poc
    part = K.loop_parts(produit)[0]
    what = _poc_case(admin, poc, swap=(part, _replacement(produit, part, same_family=False)))
    groups = {c["group"] for c in cbom["configurable"] if c["to"] == part}
    assert len(groups) >= 2                                     # the loop part is shared
    assert {u["group"] for u in what["unsatisfied"]} == groups


def test_poc_loose_variant_prunes_like_the_oracle(admin, poc):
    """No constraint at all: every option is resolved, 5.3 keeps the best-scoring one per ConfigGroup."""
    cy = _poc_case(admin, poc, constraints=[])
    assert cy["unsatisfied"] == []
    assert sum(1 for x in cy["links"] if x["relType"] == "HAS_OPTION") == len(poc[1]["groups"])


# ---------- gateway ----------
@pytest.fixture
def poc_world(world, tq, admin, kgtest):
    tq("MATCH (k:KnowledgeGraph {id: 'produit'}) SET k.dbName = $kgdb", kgdb=KGTEST)
    produit, cbom = load_poc(admin, kgtest)
    yield world, produit, cbom
    tq("MATCH (k:KnowledgeGraph {id: 'produit'}) SET k.dbName = 'kgproduit'")
    with admin.session(database=kgtest) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()


def _committee(w, boss):
    ps = [w.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    w.send_to(boss, "inbox:t-comite")
    return ps


def _expected_impact(admin, produit, cbom, part, repl):
    base = _cypher_variant(admin, KGTEST, cbom["product"], "b", poc_selection(cbom))
    what = _cypher_variant(admin, KGTEST, cbom["product"], "w", poc_selection(cbom, (part, repl)))
    return round(what["cost"] - base["cost"], 2), round(what["weight"] - base["weight"], 3), what


def test_approval_freezes_the_server_computed_impact(client, poc_world, tq, admin):
    w, produit, cbom = poc_world
    part = K.loop_parts(produit)[0]
    repl = _replacement(produit, part)
    boss = w.agent("t-boss", tools=[("launch_modification", "2-of-3")], kgs=["produit"])
    ps = _committee(w, boss)
    sid = w.session(boss, chain="c-cbom")
    r = w.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L1", "electorate": "inbox:t-comite",
                                    "args": {"part_id": part, "replacement_id": repl, "description": "d",
                                             "impact": {"costDelta": -1e9}}})          # an agent-supplied impact is discarded
    assert r.status_code == 201, r.text
    cost_d, weight_d, what = _expected_impact(admin, produit, cbom, part, repl)
    imp = r.json()["impact"]
    assert imp["available"] and imp["complete"] and imp["unsatisfied"] == []
    assert imp["costDelta"] == cost_d and imp["weightDelta"] == weight_d
    frozen = json.loads(tq("MATCH (:Approval {id: $id})-[:FOR]->(tc:ToolCall) RETURN tc.args AS a", id=r.json()["id"])[0]["a"])
    assert frozen["impact"] == imp and len(json.dumps(frozen)) <= 4000
    # the committee sees it in its pending approvals
    pend = w.c.get("/approvals", headers=tok("user", ps[0])).json()["approvals"]
    assert [a["args"]["impact"] for a in pend if a["id"] == r.json()["id"]] == [imp]
    # approved and launched: the released BOM becomes the what-if
    for p in ps[:2]:
        w.post(f"/approvals/{r.json()['id']}/votes", p, {"decision": "approve"}, kind="user")
    assert w.post("/modifications/launch", boss, {"sessionId": sid, "toolCallKey": "L1"}).status_code == 200
    with admin.session(database=KGTEST) as s:
        sel = s.run("CYPHER 25 MATCH (g:ConfigGroup) OPTIONAL MATCH (:Part)-[c:CONTAINS {group: g.id}]->(x) WHERE c.removedIn IS NULL "
                    "RETURN g.category AS category, collect(x.id) AS selected").data()
    from orchestra.gateway.cbom import constraints
    after = _cypher_variant(admin, KGTEST, cbom["product"], "a", constraints(sel))
    assert after["cost"] == pytest.approx(what["cost"]) and after["weight"] == pytest.approx(what["weight"])


def test_approval_with_a_replacement_outside_the_options(client, poc_world):
    w, produit, cbom = poc_world
    part = K.loop_parts(produit)[0]
    boss = w.agent("t-boss", tools=[("launch_modification", "2-of-3")], kgs=["produit"])
    _committee(w, boss)
    sid = w.session(boss)
    r = w.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L1", "electorate": "inbox:t-comite",
                                    "args": {"part_id": part, "replacement_id": _replacement(produit, part, same_family=False)}})
    imp = r.json()["impact"]
    assert imp["available"] and not imp["complete"] and len(imp["unsatisfied"]) >= 2


def test_approval_without_cbom_or_without_kg_right_still_goes_to_the_committee(client, kg_world):
    w = kg_world                                          # minimal BOM: no Product / ConfigGroup
    boss = w.agent("t-boss", tools=[("launch_modification", "2-of-3")], kgs=["produit"])
    blind = w.agent("t-blind", tools=[("launch_modification", "2-of-3")])
    _committee(w, boss)
    w.send_to(blind, "inbox:t-comite")
    for a in (boss, blind):
        sid = w.session(a)
        r = w.post("/approvals", a, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L1", "electorate": "inbox:t-comite",
                                     "args": {"part_id": "X1", "replacement_id": "X2"}})
        assert r.status_code == 201 and r.json()["impact"]["available"] is False


def test_evaluate_change_requires_the_tool_and_matches_the_approval_computation(client, poc_world, admin):
    w, produit, cbom = poc_world
    part = K.loop_parts(produit)[0]
    repl = _replacement(produit, part)
    eng = w.agent("t-eng", tools=["evaluate_change"], kgs=["produit"])
    nope = w.agent("t-nope", kgs=["produit"])
    body = lambda sid: {"sessionId": sid, "partId": part, "replacementId": repl}
    assert w.post("/kg/impact", nope, body(w.session(nope))).status_code == 403
    r = w.post("/kg/impact", eng, body(w.session(eng)))
    assert r.status_code == 200, r.text
    cost_d, weight_d, _ = _expected_impact(admin, produit, cbom, part, repl)
    assert (r.json()["costDelta"], r.json()["weightDelta"]) == (cost_d, weight_d)
    assert w.post("/kg/impact", eng, {**body(w.session(eng)), "partId": cbom["product"]}).json()["available"] is False
