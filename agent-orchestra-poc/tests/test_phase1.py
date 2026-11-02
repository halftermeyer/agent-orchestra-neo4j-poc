import json

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ClientError

from orchestra import config
from orchestra.seed import kg_data as K
from orchestra.seed import load


def test_generator_is_deterministic():
    a, b = K.generate_kg_produit(), K.generate_kg_produit()
    assert a == b
    assert K.generate_incidents(a) == K.generate_incidents(b)
    assert K.generate_kg_produit(seed=1) != a


def test_generator_sizes():
    p = K.generate_kg_produit()
    assert len(p["parts"]) == 200 and len({x["id"] for x in p["parts"]}) == 200
    assert {x["level"] for x in p["parts"]} == {0, 1, 2, 3}
    assert len(p["tests"]) == 50
    j = K.generate_kg_projet(p["tests"], [x["id"] for x in p["parts"] if x["level"] == 1])
    assert len(j["tasks"]) == 30
    assert len(K.generate_incidents(p)) == 10


def test_databases_and_users(q):
    dbs = {r["name"]: r["currentStatus"] for r in q("system", "SHOW DATABASES YIELD name, currentStatus RETURN name, currentStatus")}
    for name in ("orchestra", "kgproduit", "kgprojet", "fed"):
        assert dbs.get(name) == "online"
    users = {r["user"] for r in q("system", "SHOW USERS YIELD user RETURN user")}
    assert {"admin", "gateway", "cdc"} <= users
    opts = q("system", "SHOW DATABASES YIELD name, options WHERE name IN ['orchestra','kgproduit','kgprojet'] RETURN options")
    assert all(o["options"].get("txLogEnrichment") == "FULL" for o in opts)


def test_cdc_user_minimal_privileges():
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.CDC_USER, config.CDC_PASSWORD)) as d:
        with d.session(database="orchestra") as s:
            s.run("CALL db.cdc.current() YIELD id RETURN id").consume()
            # no MATCH right: direct reads return nothing
            assert s.run("MATCH (n) RETURN count(n) AS n").single()["n"] == 0
            with pytest.raises(ClientError):
                s.run("CREATE (:Agent {id: 'x'})").consume()


def test_gateway_cannot_write_kg():
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.GATEWAY_USER, config.GATEWAY_PASSWORD)) as d:
        with d.session(database="kgproduit") as s:
            assert s.run("MATCH (n:Part) RETURN count(n) AS n").single()["n"] == 200
            with pytest.raises(ClientError):
                s.run("CREATE (:Part {id: 'X'})").consume()
        with d.session(database="orchestra") as s:
            s.run("CYPHER 25 MERGE (:Probe {id: 'gw'}) ").consume()
            s.run("MATCH (n:Probe {id: 'gw'}) DELETE n").consume()


def test_constraints_and_vector_index(q):
    names = {r["name"] for r in q("orchestra", "SHOW CONSTRAINTS YIELD name RETURN name")}
    assert {"inboxday_key", "workday_key", "message_key", "session_key", "agent_key", "vote_once", "entityref_key", "toolcall_key", "approval_key"} <= names
    idx = q("orchestra", "SHOW INDEXES YIELD name, type, state WHERE name = 'fact_embedding' RETURN type, state")
    assert idx and idx[0]["type"] == "VECTOR" and idx[0]["state"] == "ONLINE"


def test_node_key_and_unique_enforced(q):
    q("orchestra", "MERGE (:Inbox {id: 'inbox:t'})-[:HAS_DAY]->(:Day:InboxDay {inboxId: 'inbox:t', date: date('2026-01-01')})")
    with pytest.raises(ClientError):
        q("orchestra", "CREATE (:Day:InboxDay {inboxId: 'inbox:t', date: date('2026-01-01')})")
    with pytest.raises(ClientError):
        q("orchestra", "CREATE (:Message {id: 'm1'}), (:Message {id: 'm1'})")
    q("orchestra", "MATCH (n) WHERE n.id = 'inbox:t' OR n.inboxId = 'inbox:t' DETACH DELETE n")
    q("orchestra", "MATCH (m:Message {id: 'm1'}) DELETE m")


def test_vote_unique_per_person(q):
    q("orchestra", "MERGE (:Approval {id: 'ap-t'}) MERGE (:Agent:Person {id: 'p-t'})")
    mk = "MATCH (a:Approval {id: 'ap-t'}), (p:Agent:Person {id: 'p-t'}) CREATE (p)-[:VOTED {approvalId: 'ap-t', personId: 'p-t', decision: 'yes'}]->(a)"
    q("orchestra", mk)
    with pytest.raises(ClientError):
        q("orchestra", mk)
    q("orchestra", "MATCH (n) WHERE n.id IN ['ap-t', 'p-t'] DETACH DELETE n")


def test_seed_is_idempotent(q):
    count = "MATCH (n) WITH count(n) AS n MATCH ()-[r]->() RETURN n, count(r) AS r"
    before = [q(db, count)[0] for db in ("orchestra", "kgproduit", "kgprojet")]
    load.run_all()
    after = [q(db, count)[0] for db in ("orchestra", "kgproduit", "kgprojet")]
    assert before == after


def test_scenario_actors(q):
    r = q("orchestra", "MATCH (a:Agent:SoftwareAgent) RETURN collect(a.id) AS ids")[0]["ids"]
    assert set(r) == {"coordinateur", "qualite", "ingenierie", "essais", "planification", "pont-kg", "interpreteur-bom", "auditeur"}
    r = q("orchestra", "MATCH (a:Agent:Person) RETURN collect(a.id) AS ids")[0]["ids"]
    assert set(r) == {"ing-qualite", "comite-1", "comite-2", "comite-3", "chef-projet"}
    # every software agent has a mandate, current version; rules have no model
    assert q("orchestra", "MATCH (a:Agent:SoftwareAgent) WHERE NOT (a)-[:HAS_MANDATE]->(:Mandate) OR NOT (a)-[:CURRENT]->(:AgentVersion) RETURN count(a) AS n")[0]["n"] == 0
    assert q("orchestra", "MATCH (:Agent {id: 'pont-kg'})-[:CURRENT]->(v) RETURN v.kind AS k, v.model AS m")[0] == {"k": "rule", "m": None}
    # committee's shared inbox
    assert q("orchestra", "MATCH (p:Agent:Person)-[:HAS_INBOX]->(i:Inbox {id: 'inbox:comite'}) RETURN count(p) AS n")[0]["n"] == 3
    topics = {r["id"] for r in q("orchestra", "MATCH (t:Inbox:Topic) RETURN t.id AS id")}
    assert topics == {"incidents", "kg.produit.raw", "produit.bom-changes"}


def test_supervision_rules(q):
    # no cycle: no agent is reached from itself via at least one SUPERVISES
    assert q("orchestra", "MATCH ACYCLIC (a:Agent)-[:SUPERVISES]->+(b:Agent) WHERE a = b RETURN count(*) AS n")[0]["n"] == 0
    assert q("orchestra", "MATCH (a:Agent)-[:SUPERVISES]->+(a) RETURN count(*) AS n")[0]["n"] == 0
    # a software agent does not supervise a human
    assert q("orchestra", "MATCH (:SoftwareAgent)-[:SUPERVISES]->(:Person) RETURN count(*) AS n")[0]["n"] == 0
    scope = q("orchestra", "MATCH ACYCLIC (:Agent {id: 'coordinateur'})-[:SUPERVISES]->*(a) RETURN collect(a.id) AS ids")[0]["ids"]
    assert set(scope) >= {"coordinateur", "ingenierie", "essais", "planification"}
    assert "qualite" not in scope and "comite-1" not in scope


def test_send_targets_and_tool_rights(q):
    assert q("orchestra", "MATCH (:Agent)-[:CAN_SEND_TO]->(x) WHERE NOT x:Inbox RETURN count(x) AS n")[0]["n"] == 0
    # the usage right is not inherited: the irreversible tool is only with the coordinator
    users = q("orchestra", "MATCH (a)-[c:CAN_USE]->(:Tool {name: 'launch_modification'}) RETURN a.id AS id, c.approval AS ap")
    assert users == [{"id": "coordinateur", "ap": "2-of-3"}]
    assert q("orchestra", "MATCH (a)-[:CAN_USE]->(:Tool {name: 'cpa_simulate'}) RETURN collect(a.id) AS ids")[0]["ids"] == ["planification"]


def test_routines(q):
    rows = q("orchestra", """MATCH (a)-[:OWNS]->(r:Routine)-[:DELIVERS_TO]->(i:Inbox)
                              OPTIONAL MATCH (r)-[:LISTENS_TO]->(t:Topic)
                              RETURN r.id AS id, r.trigger AS tr, r.misfire AS mf, t.id AS topic, i.id AS inbox, r.filter AS f""")
    assert len(rows) == 5 and all(r["mf"] == "skip" for r in rows)
    for r in rows:
        if r["tr"] == "event":
            assert r["topic"] and json.loads(r["f"])["op"] == "eq"
    # each routine delivers into an inbox its owner can reach (CAN_SEND_TO or its own)
    bad = q("orchestra", """MATCH (a)-[:OWNS]->(r:Routine)-[:DELIVERS_TO]->(i:Inbox)
                            WHERE NOT (a)-[:HAS_INBOX]->(i) AND NOT (a)-[:CAN_SEND_TO]->(i) RETURN count(r) AS n""")[0]["n"]
    assert bad == 0


def test_kg_content(q):
    assert q("kgproduit", "MATCH (p:Part) RETURN count(p) AS n")[0]["n"] == 200
    assert q("kgproduit", "MATCH (t:Test) RETURN count(t) AS n")[0]["n"] == 50
    assert q("kgproduit", "MATCH (v:ProductVersion {current: true}) RETURN v.label AS l")[0]["l"] == "v1.0"
    # the BOM is a DAG: no cycle
    assert q("kgproduit", "MATCH (p:Part)-[:CONTAINS]->+(p) RETURN count(*) AS n")[0]["n"] == 0
    # shared parts (multiple use) exist
    assert q("kgproduit", "MATCH (p:Part)<-[:CONTAINS]-(x) WITH p, count(x) AS c WHERE c > 1 RETURN count(p) AS n")[0]["n"] >= 20
    assert q("kgprojet", "MATCH (t:Task) RETURN count(t) AS n")[0]["n"] == 30
    assert q("kgprojet", "MATCH (t:Task)-[:DEPENDS_ON]->+(t) RETURN count(*) AS n")[0]["n"] == 0


def test_federated_query(q):
    rows = q("fed", """UNWIND ['kgproduit', 'kgprojet'] AS g
                       CALL (g) { USE graph.byName('fed.' + g) MATCH (e:Entity) RETURN count(e) AS n }
                       RETURN g, n ORDER BY g""")
    assert rows[0]["n"] > 200 and rows[1]["n"] == 38


def test_incidents_file_matches_kg(q):
    inc = json.loads((load.DATA_DIR / "incidents.json").read_text(encoding="utf-8"))
    assert len(inc) == 10
    ids = {r["id"] for r in q("kgproduit", "MATCH (p:Part) RETURN p.id AS id")}
    assert all(i["componentId"] in ids for i in inc)


def test_first_incident_provokes_the_legitimate_engineering_tests_loop():
    """INC-001 must lead to proposing a part without tests (refused) then a covered part (accepted): see the scenario."""
    p = K.generate_kg_produit()
    inc = K.generate_incidents(p)
    loop = K.loop_parts(p)
    assert inc[0]["componentId"] == loop[0] and len(loop) >= 1
    parts, parents, tests_of, candidates = K._bom_index(p)
    c = candidates(inc[0]["componentId"])
    assert tests_of(inc[0]["componentId"]) and not tests_of(c[0]) and tests_of(c[1])
    assert len({i["componentId"] for i in inc}) == 10
