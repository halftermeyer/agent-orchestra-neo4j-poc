"""CBOM test data: the bike of the configurable-bom page and the PoC seed, as Neo4j loads and as oracle input."""
import json
from pathlib import Path

from orchestra.seed import kg_data as K
from orchestra.seed.load import load_cbom, load_kg_produit

BIKE = json.loads((Path(__file__).parent / "fixtures" / "cbom_bike.json").read_text())
REL_OF = {"HAS_PART": "CONTAINS"}           # the PoC's CONTAINS plays the page's HAS_PART


def bike_oracle_input():
    nodes = {n["id"]: {"labels": set(n["labels"]), **n["properties"]} for n in BIKE["nodes"]}
    edges = [(e["start"], REL_OF.get(e["type"], e["type"]), e["end"], e["properties"]) for e in BIKE["edges"]]
    return nodes, edges


def load_bike(admin, db):
    with admin.session(database=db) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()
        for label in ("Product", "Assembly", "ConfigGroup", "Part"):
            rows = [{"id": n["id"], "p": n["properties"]} for n in BIKE["nodes"] if n["labels"] == [label]]
            s.run(f"CYPHER 25 UNWIND $rows AS r CREATE (n:Entity:{label} {{id: r.id}}) SET n += r.p", rows=rows).consume()
        for typ in {e["type"] for e in BIKE["edges"]}:
            rows = [{"s": e["start"], "e": e["end"], "p": e["properties"]} for e in BIKE["edges"] if e["type"] == typ]
            s.run(f"CYPHER 25 UNWIND $rows AS r MATCH (a:Entity {{id: r.s}}), (b:Entity {{id: r.e}}) "
                  f"CREATE (a)-[x:{REL_OF.get(typ, typ)}]->(b) SET x += r.p", rows=rows).consume()


def poc_data():
    produit = K.generate_kg_produit()
    return produit, K.generate_cbom(produit)


def load_poc(admin, db):
    produit, cbom = poc_data()
    with admin.session(database=db) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()
        s.run("CYPHER 25 CREATE (:Entity:ProductVersion {id: 'VER-1.0', label: 'v1.0', current: true})").consume()
    load_kg_produit(admin, produit, db=db)
    load_cbom(admin, cbom, db=db)
    return produit, cbom


def poc_oracle_input(produit, cbom, removed=()):
    """Oracle view of the PoC CBOM. Labels as the page sees them (assemblies are not leaves)."""
    nodes = {}
    for p in produit["parts"]:
        lab = "Product" if p["id"] == cbom["product"] else "Assembly" if p["level"] in (1, 2) else "Part"
        nodes[p["id"]] = {"labels": {lab}, **p}
    for g in cbom["groups"]:
        nodes[g["id"]] = {"labels": {"ConfigGroup"}, **g}
    flagged = {(c["from"], c["to"]) for c in cbom["configurable"]}
    edges = [(c["from"], "CONTAINS", c["to"], {"qty": c["qty"]}) for c in produit["contains"] if (c["from"], c["to"]) not in flagged]
    edges += [(r["from"], "REQUIRES", r["to"], {"qty": r["qty"], "note": r["note"]}) for r in cbom["requires"]]
    edges += [(o["from"], "HAS_OPTION", o["to"], {}) for o in cbom["options"]]
    return nodes, edges


def poc_selection(cbom, swap=None):
    """Baseline constraints as the gateway builds them (one allow_list on `id` per ConfigGroup)."""
    sel = [{"category": g["id"], "selected": [c["to"] for c in cbom["configurable"] if c["group"] == g["id"]]} for g in cbom["groups"]]
    from orchestra.gateway.cbom import constraints
    return constraints(sel, swap)
