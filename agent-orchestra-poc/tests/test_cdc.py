import json
import statistics
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from neo4j import GraphDatabase, unit_of_work
from starlette.testclient import TestClient

from orchestra import config, predicate
from orchestra.cdc.app import create_app
from orchestra.cdc.cursors import CursorStore
from orchestra.cdc.gateway_client import GatewayClient, GatewayError
from orchestra.cdc.scheduler import iso, next_after
from tests.conftest import KGTEST, MASTER, tok

UTC = timezone.utc


# ---------- structured predicates ----------
def test_predicate_grammar():
    p = {"all": [{"field": "kind", "op": "eq", "value": "incident"}, {"field": "a.b", "op": "in", "value": [1, 2]},
                 {"not": {"field": "msg.from", "op": "eq", "value": "x"}}]}
    predicate.validate(p)
    assert predicate.evaluate(p, {"kind": "incident", "a": {"b": 2}}, {"from": "y"})
    assert not predicate.evaluate(p, {"kind": "incident", "a": {"b": 3}}, {"from": "y"})
    assert not predicate.evaluate(p, {"kind": "incident", "a": {"b": 1}}, {"from": "x"})
    assert predicate.evaluate({"field": "z", "op": "exists", "value": False}, {}, {})
    assert predicate.evaluate({"any": [{"field": "n", "op": "gt", "value": 3}, {"field": "k", "op": "prefix", "value": "ab"}]}, {"k": "abc"}, {})
    for bad in ({"field": "x", "op": "cypher", "value": "MATCH (n)"}, {"all": []}, {"field": "x"}, [], {"not": 1}):
        with pytest.raises(ValueError):
            predicate.validate(bad)


# ---------- curseur ----------
def test_cursor_store_is_atomic_and_per_db(tmp_path):
    c = CursorStore(tmp_path / "c.json")
    assert c.get("a") is None
    c.set("a", "1"); c.set("b", "2"); c.set("a", "3")
    assert CursorStore(tmp_path / "c.json").get("a") == "3" and c.get("b") == "2"


def test_first_start_does_not_replay_history(cdc, world, tmp_path, gw_url):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a)
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201     # before the second consumer starts
    from orchestra.cdc.consumer import Consumer
    from orchestra.cdc.hub import Hub
    from orchestra.cdc.source import CdcSource
    st = cdc.settings
    hub = Hub()
    seen = []
    hub.on_event(seen.append)
    c2 = Consumer(st, CdcSource(st.neo4j_uri, st.neo4j_user, st.neo4j_password), cdc.gw, CursorStore(tmp_path / "fresh.json"), hub)
    c2.init_cursors()
    assert c2.poll_once() == 0 and not seen


def test_cursor_from_a_recreated_database_is_reset_not_stuck(cdc, world):
    # a cursor more recent than the log (database recreated under a consumer left running)
    c = cdc.consumer
    db = cdc.settings.orchestra_db
    for _ in range(3):
        world.agent(f"t-x{_}")
    real = c.source.current("orchestra")                                  # position of the real database, much further ahead
    c.cursors.set(db, real)
    assert c.poll_db(db) == 0                                              # no error loop: reset
    assert c.stats.cursor_resets == 1 and c.cursors.get(db) == c.source.current(db)
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    mid = world.send(a, world.session(a), ["inbox:t-b"]).json()["id"]
    cdc.drain()
    assert cdc.of("woken", messageId=mid)                                  # and processing resumes normally


def test_restart_resumes_from_persisted_cursor_and_retries_when_gateway_is_down(cdc, world, gw_url):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a)
    m1 = world.send(a, sid, ["inbox:t-b"]).json()["id"]
    cdc.drain()
    assert cdc.of("woken", messageId=m1)
    # new consumer, same cursor file: does not replay m1
    from orchestra.cdc.consumer import Consumer
    from orchestra.cdc.hub import Hub
    from orchestra.cdc.source import CdcSource
    st = cdc.settings
    hub = Hub()
    seen = []
    hub.on_event(seen.append)
    dead = GatewayClient("http://127.0.0.1:9", st.sys_token)
    c2 = Consumer(st, CdcSource(st.neo4j_uri, st.neo4j_user, st.neo4j_password), dead, cdc.consumer.cursors, hub)
    m2 = world.send(a, sid, ["inbox:t-b"]).json()["id"]
    before = c2.cursors.get(st.orchestra_db)
    with pytest.raises(GatewayError):
        c2.poll_db(st.orchestra_db)                                  # passerelle injoignable : transitoire
    assert c2.cursors.get(st.orchestra_db) == before                 # the cursor does not advance
    c2.gw = cdc.gw
    while c2.poll_once():
        pass
    woken = {e["payload"]["messageId"] for e in seen if e["type"] == "woken"}
    assert woken == {m2}


# ---------- wake-up ----------
def test_received_wakes_the_recipient_and_streams_sent(cdc, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a)
    mid = world.send(a, sid, ["inbox:t-b"], performative="request").json()["id"]
    cdc.drain()
    sent = cdc.of("sent", messageId=mid)
    assert len(sent) == 1 and sent[0]["actor"] == a and sent[0]["target"] == b
    assert sent[0]["payload"]["performative"] == "request" and sent[0]["t"]
    assert cdc.of("woken", messageId=mid)[0]["actor"] == b
    assert [w for w in cdc.wakes if w[1]["messageId"] == mid] == [(b, {"messageId": mid, "performative": "request",
                                                                       "chainId": sent[0]["payload"]["chainId"], "inbox": "inbox:t-b"})]


def test_no_wake_for_quarantined_agent_or_suspended_chain(cdc, world, tq):
    a, b, c = world.agent("t-a"), world.agent("t-b"), world.agent("t-c")
    world.send_to(a, "inbox:t-b", "inbox:t-c")
    sid = world.session(a, chain="c-susp")
    tq("MATCH (x:Agent {id: 't-b'}) SET x.quarantined = true")
    m1 = world.send(a, sid, ["inbox:t-b"]).json()["id"]
    cdc.drain()
    assert cdc.of("sent", messageId=m1) and not cdc.of("woken", messageId=m1)
    # chain suspended after the drop (budget exhausted or auditor): no wake-up either
    m2 = world.send(a, sid, ["inbox:t-c"]).json()["id"]
    tq("MATCH (ch:Chain {id: 'c-susp'}) SET ch.status = 'suspended'")
    cdc.drain()
    assert not cdc.of("woken", messageId=m2) and not [w for w in cdc.wakes if w[1]["messageId"] in (m1, m2)]


def test_humans_are_woken_in_the_stream_but_not_via_runtime(cdc, world):
    a, p = world.agent("t-a"), world.agent("t-p", person=True)
    world.send_to(a, "inbox:t-p")
    sid = world.session(a)
    mid = world.send(a, sid, ["inbox:t-p"]).json()["id"]
    cdc.drain()
    assert cdc.of("woken", messageId=mid)[0]["actor"] == p
    assert not [w for w in cdc.wakes if w[1]["messageId"] == mid]


# ---------- topic routing ----------
def _publish_incident(world, payload, user="ing-qualite"):
    r = world.c.post("/messages", json={"to": ["incidents"], "performative": "inform", "body": "Leak detected", "payload": payload},
                     headers=tok("user", user))
    assert r.status_code == 201, r.text
    return r.json()


def test_topic_routing_delivers_matching_events_only(cdc, world, tq):
    inc = _publish_incident(world, {"kind": "incident", "componentId": "PRT-0045", "severity": "critique"})
    _publish_incident(world, {"kind": "autre chose"})
    cdc.drain()
    rows = tq("""MATCH (:Inbox {id: 'inbox:qualite'})-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m:Message)
                 OPTIONAL MATCH (m)-[:ABOUT_EVENT]->(e:Message)
                 RETURN m.id AS id, m.from AS f, m.chainId AS chain, e.id AS about, r.status AS st, m.actingAgent AS acting, m.body AS body""")
    assert len(rows) == 1
    r = rows[0]
    assert r["f"] == "routine:rt-qualite-incidents" and r["chain"] == inc["chainId"] and r["about"] == inc["id"]
    assert r["st"] == "submitted" and r["acting"] == "qualite" and r["body"] == "Leak detected"
    assert r["id"] == f"evt:rt-qualite-incidents:{inc['id']}"
    assert cdc.of("woken", actor="qualite") and [w for w in cdc.wakes if w[0] == "qualite"]
    topic_sent = cdc.of("sent", messageId=inc["id"])
    assert topic_sent[0]["target"] == "incidents" and topic_sent[0]["payload"]["topic"] is True
    # the payload is kept for the following filters
    got = tq("MATCH (m:Message {id: $id}) RETURN m.payloadJson AS p", id=r["id"])[0]["p"]
    assert json.loads(got)["componentId"] == "PRT-0045"


def test_routing_is_idempotent_on_replay(cdc, world, tq):
    _publish_incident(world, {"kind": "incident"})
    cdc.drain()
    count = "MATCH (m:Message {from: 'routine:rt-qualite-incidents'}) RETURN count(m) AS n"
    assert tq(count)[0]["n"] == 1
    # replay from the start of the log: same deterministic message ids, no duplicates
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.CDC_USER, config.CDC_PASSWORD)) as d:
        with d.session(database=cdc.settings.orchestra_db) as s:
            earliest = s.run("CALL db.cdc.earliest() YIELD id RETURN id").single()["id"]
    cdc.consumer.cursors.set(cdc.settings.orchestra_db, earliest)
    cdc.drain()
    assert tq(count)[0]["n"] == 1


def test_routing_respects_chain_budget_and_send_rights(cdc, world, tq):
    # budget exhausted: delivery is refused by the gateway, the chain is suspended
    assert world.c.post("/chains", json={"id": "c-full", "budget": 1, "tokenBudget": 1000}, headers=tok("admin")).status_code == 201
    r = world.c.post("/messages", json={"to": ["incidents"], "performative": "inform", "body": "x", "chainId": "c-full",
                                        "payload": {"kind": "incident"}}, headers=tok("user", "ing-qualite"))
    assert r.status_code == 201
    cdc.drain()
    assert tq("MATCH (m:Message {from: 'routine:rt-qualite-incidents'}) RETURN count(m) AS n")[0]["n"] == 0
    assert tq("MATCH (c:Chain {id: 'c-full'}) RETURN c.status AS s")[0]["s"] == "suspended"
    err = cdc.of("error", actor="qualite")
    assert err and err[0]["payload"]["status"] == 429
    # "an exhausted budget suspends the chain and sends it to the auditor": system message in its inbox
    note = tq("""MATCH (:Inbox {id: 'inbox:auditeur'})-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m:Message {id: 'chain-suspended:c-full'})
                 RETURN m.from AS f, m.payloadJson AS p""")
    assert len(note) == 1 and note[0]["f"] == "gateway" and json.loads(note[0]["p"])["reason"] == "budget"
    assert [w for w in cdc.wakes if w[0] == "auditeur" and w[1]["messageId"] == "chain-suspended:c-full"]
    # a quarantined agent no longer receives routed events
    tq("MATCH (a:Agent {id: 'qualite'}) SET a.quarantined = true")
    _publish_incident(world, {"kind": "incident"})
    cdc.drain()
    assert tq("MATCH (m:Message {from: 'routine:rt-qualite-incidents'}) RETURN count(m) AS n")[0]["n"] == 0


def test_agent_does_not_consume_its_own_publications(cdc, world, tq):
    a = world.agent("t-a")
    world.send_to(a, "produit.bom-changes")
    tq("""MATCH (a:Agent {id: 't-a'}), (t:Inbox:Topic {id: 'produit.bom-changes'}), (i:Inbox {id: 'inbox:t-a'})
          CREATE (a)-[:OWNS]->(r:Routine {id: 'rt-t-self', trigger: 'event', enabled: true, misfire: 'skip', test: true,
                                          filter: '{"field":"kind","op":"eq","value":"bom-change"}'})
          CREATE (r)-[:LISTENS_TO]->(t) CREATE (r)-[:DELIVERS_TO]->(i)""")
    sid = world.session(a)
    assert world.send(a, sid, ["produit.bom-changes"], payload={"kind": "bom-change"}).status_code == 201
    cdc.drain()
    assert tq("MATCH (m:Message {from: 'routine:rt-t-self'}) RETURN count(m) AS n")[0]["n"] == 0
    # testing and planning, subscribed to the same topic, do receive the event
    assert tq("MATCH (m:Message) WHERE m.from IN ['routine:rt-essais-bom', 'routine:rt-planif-bom'] RETURN count(m) AS n")[0]["n"] == 2


# ---------- pont KG ----------
def _kg_write(admin, db, cypher, chain=None, **p):
    @unit_of_work(metadata={"chainId": chain} if chain else {})
    def work(tx):
        tx.run("CYPHER 25\n" + cypher, p).consume()
    with admin.session(database=db) as s:
        s.execute_write(work)


def test_kg_bridge_one_message_per_transaction(cdc, admin, tq):
    _kg_write(admin, KGTEST, "CREATE (a:Entity:Part {id: 'B1', name: 'Un'}), (b:Entity:Part {id: 'B2', name: 'Deux'}), (a)-[:CONTAINS]->(b)")
    _kg_write(admin, KGTEST, "MATCH (a:Entity {id: 'B1'}) SET a.revision = 'B'", chain="chain-modif")
    cdc.drain()
    rows = tq("""MATCH (:Inbox:Topic {id: 'kg.produit.raw'})-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m:Message)
                 RETURN m.id AS id, m.from AS f, m.chainId AS chain, m.payloadJson AS p ORDER BY m.createdAt""")
    assert len(rows) == 2
    first, second = rows
    p1, p2 = json.loads(first["p"]), json.loads(second["p"])
    assert first["f"] == "pont-kg" and first["id"] == f"raw:{KGTEST}:{p1['txId']}"
    assert p1["kind"] == "kg-raw" and p1["kgDb"] == KGTEST and p1["changeCount"] == 3
    assert {c["entityId"] for c in p1["changes"] if c["kind"] == "node"} == {"B1", "B2"}
    assert [c for c in p1["changes"] if c["kind"] == "rel"][0]["type"] == "CONTAINS"
    assert p2["changeCount"] == 1 and p2["changes"][0]["op"] == "u" and p2["changes"][0]["entityId"] == "B1"
    assert second["chain"] == "chain-modif"          # the causal chain is taken from the txMetadata
    # replay: no duplicate
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.CDC_USER, config.CDC_PASSWORD)) as d:
        with d.session(database=KGTEST) as s:
            earliest = s.run("CALL db.cdc.earliest() YIELD id RETURN id").single()["id"]
    cdc.consumer.cursors.set(KGTEST, earliest)
    cdc.drain()
    assert tq("MATCH (m:Message {from: 'pont-kg'}) RETURN count(m) AS n")[0]["n"] >= 2
    assert tq("MATCH (m:Message) WHERE m.id STARTS WITH $p RETURN count(DISTINCT m.id) = count(m) AS ok", p=f"raw:{KGTEST}:")[0]["ok"]
    # the interpreter routine's filter (kgDb = kgproduit) discards this test database
    assert tq("MATCH (m:Message {from: 'routine:rt-interp-raw'}) RETURN count(m) AS n")[0]["n"] == 0


def test_raw_topic_routes_to_the_bom_interpreter(cdc, world, tq):
    a = world.agent("t-a")
    world.send_to(a, "kg.produit.raw")
    sid = world.session(a)
    assert world.send(a, sid, ["kg.produit.raw"], payload={"kind": "kg-raw", "kgDb": "kgproduit", "txId": 1}).status_code == 201
    assert world.send(a, sid, ["kg.produit.raw"], payload={"kind": "kg-raw", "kgDb": "kgprojet", "txId": 2}).status_code == 201
    cdc.drain()
    assert tq("MATCH (m:Message {from: 'routine:rt-interp-raw'}) RETURN count(m) AS n")[0]["n"] == 1
    assert [w for w in cdc.wakes if w[0] == "interpreteur-bom"]


# ---------- EntityRef ----------
def test_entityref_lifecycle_follows_the_kg(cdc, admin, tq):
    tq("""MATCH (k:KnowledgeGraph {id: 'produit'})
          MERGE (r:Ref:EntityRef {db: $kgdb, key: 'E1'}) ON CREATE SET r.label = 'Ancien', r.labelAt = datetime() - duration('P1D'), r.test = true
          MERGE (r)-[:IN_KG]->(k)""", kgdb=KGTEST)
    _kg_write(admin, KGTEST, "CREATE (:Entity:Part {id: 'E1', name: 'Ancien'}), (:Entity:Part {id: 'E2', name: 'Cible'})")
    _kg_write(admin, KGTEST, "MATCH (e:Entity {id: 'E1'}) SET e.name = 'New name'")
    cdc.drain()
    r = tq("MATCH (r:EntityRef {db: $kgdb, key: 'E1'}) RETURN r.label AS l, r.labelAt > datetime() - duration('PT1H') AS fresh", kgdb=KGTEST)[0]
    assert r == {"l": "New name", "fresh": True}
    # merge: E1 SAME_AS E2 -> proxy redirection
    _kg_write(admin, KGTEST, "MATCH (a:Entity {id: 'E1'}), (b:Entity {id: 'E2'}) CREATE (a)-[:SAME_AS]->(b)")
    cdc.drain()
    red = tq("""MATCH (old:EntityRef {db: $kgdb, key: 'E1'})-[:SAME_AS]->(new:EntityRef {key: 'E2'})-[:IN_KG]->(:KnowledgeGraph {id: 'produit'})
                RETURN old.redirectedAt IS NOT NULL AS red, new.label AS l""", kgdb=KGTEST)
    assert red == [{"red": True, "l": "New name"}]
    assert tq("MATCH (r:EntityRef {db: $kgdb, key: 'E1'}) OPTIONAL MATCH (r)-[:SAME_AS]->+(t) RETURN t.key AS k", kgdb=KGTEST)[0]["k"] == "E2"
    # suppression
    _kg_write(admin, KGTEST, "MATCH (e:Entity {id: 'E2'}) DETACH DELETE e")
    cdc.drain()
    assert tq("MATCH (r:EntityRef {db: $kgdb, key: 'E2'}) RETURN r.deletedAt IS NOT NULL AS d", kgdb=KGTEST)[0]["d"]
    tq("MATCH (r:EntityRef {db: $kgdb}) DETACH DELETE r", kgdb=KGTEST)


# ---------- normalized stream ----------
def test_stream_covers_agent_activity(cdc, world):
    a = world.agent("t-a", tools=["query_kg", "remember"])
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "I am looking for the component"})
    world.post("/tools/calls", a, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "k1"})
    world.post("/tools/calls/k1/end", a, {"status": "completed"})
    world.post("/tools/calls", a, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "k2"})
    world.post("/tools/calls/k2/end", a, {"status": "failed", "error": "KG unavailable"})
    world.remember(a, sid, "The relay is faulty")
    world.c.post(f"/sessions/{sid}/close", json={"status": "completed"}, headers=tok("svc", a))
    cdc.drain()
    mine = [e for e in cdc.events if e["actor"] == a and e["type"] != "woken"]
    types = [e["type"] for e in mine]
    assert types == ["status", "tool.start", "tool.end", "tool.start", "error", "learned", "idle"], types
    by = {e["type"]: e for e in mine}
    assert by["status"]["payload"]["text"] == "I am looking for the component"
    assert [e["target"] for e in mine if e["type"] in ("tool.start", "tool.end")][0] == "query_kg"
    assert by["error"]["payload"]["error"] == "KG unavailable"
    assert by["learned"]["target"] == f"mem:{a}" and by["learned"]["payload"]["statement"].startswith("The relay")
    assert all(e["t"] for e in mine) and mine == sorted(mine, key=lambda e: e["t"])
    assert set(by["idle"]) == {"t", "type", "actor", "target", "payload"}


def test_stream_covers_governance(cdc, world):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss, chain="c-gov")
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "l1", "electorate": "inbox:t-comite"}).json()["id"]
    for p in ps[:2]:
        assert world.post(f"/approvals/{ap}/votes", p, {"decision": "approve"}, kind="user").status_code == 201
    world.c.post("/chains/c-gov/resume", json={}, headers=tok("admin"))
    world.c.post("/chains", json={"id": "c-loop", "budget": 1, "tokenBudget": 100}, headers=tok("admin"))
    s2 = world.session(boss, chain="c-loop")
    world.send(boss, s2, ["inbox:t-comite"]); world.send(boss, s2, ["inbox:t-comite"])        # 2nd send: budget exhausted
    cdc.drain()
    w = cdc.of("waiting", actor=boss)
    assert w and w[0]["target"] == "launch_modification"
    votes = cdc.of("vote")
    assert [(v["actor"], v["target"], v["payload"]["decision"]) for v in votes] == [("t-p1", ap, "approve"), ("t-p2", ap, "approve")]
    assert [e for e in cdc.of("tool.start", actor=boss) if e["payload"].get("resumed")]      # quorum atteint : l'appel reprend
    err = cdc.of("error", chainId="c-loop")
    assert err and err[0]["payload"]["reason"] == "budget"


# ---------- planificateur ----------
@pytest.fixture
def sched(cdc, tq):
    tq("MATCH (r:Routine {id: 'rt-auditeur-scan'}) SET r.enabled = false")   # seed routine: out of the test
    return cdc.scheduler


def _routine(world, agent, **body):
    r = world.post("/routines", agent, body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _msgs(tq, rid):
    return tq("MATCH (m:Message) WHERE m.id STARTS WITH $p RETURN m.id AS id, m.from AS f ORDER BY id", p=f"{rid}@")


def test_cron_fires_once_per_slot(cdc, world, sched, tq):
    a = world.agent("t-a")
    rid = _routine(world, a, trigger="cron", cron="*/5 * * * *", deliverTo="inbox:t-a", payload={"kind": "audit-scan", "body": "scan"})
    t0 = datetime(2026, 6, 1, 10, 2, 30, tzinfo=UTC)
    assert sched.tick(t0) == 0                                              # first sight: only schedules
    nxt = tq("MATCH (r:Routine {id: $r}) RETURN r.nextRunAt AS n", r=rid)[0]["n"].to_native()
    assert nxt == datetime(2026, 6, 1, 10, 5, tzinfo=UTC)
    assert sched.tick(t0 + timedelta(minutes=1)) == 0                       # not yet time
    assert sched.tick(datetime(2026, 6, 1, 10, 5, 3, tzinfo=UTC)) == 1
    assert [m["id"] for m in _msgs(tq, rid)] == [f"{rid}@2026-06-01T10:05:00Z"]
    assert sched.tick(datetime(2026, 6, 1, 10, 5, 4, tzinfo=UTC)) == 0      # the slot is no longer due
    # two schedulers hitting the same slot: a single message (uniqueness on Message.id)
    tq("MATCH (r:Routine {id: $r}) SET r.nextRunAt = datetime('2026-06-01T10:05:00Z')", r=rid)
    sched.tick(datetime(2026, 6, 1, 10, 5, 5, tzinfo=UTC))
    assert len(_msgs(tq, rid)) == 1
    r = tq("MATCH (r:Routine {id: $r}) RETURN r.nextRunAt AS n, r.lastFiredAt IS NOT NULL AS f", r=rid)[0]
    assert r["n"].to_native() == datetime(2026, 6, 1, 10, 10, tzinfo=UTC) and r["f"]
    cdc.drain()
    assert cdc.of("woken", actor=a)                                         # the routine wakes its owner


def test_cron_misfire_skip_ignores_missed_slots(cdc, world, sched, tq):
    a = world.agent("t-a")
    rid = _routine(world, a, trigger="cron", cron="*/5 * * * *", deliverTo="inbox:t-a")
    sched.tick(datetime(2026, 6, 1, 10, 2, tzinfo=UTC))
    late = datetime(2026, 6, 1, 14, 3, tzinfo=UTC)                          # 4 h of downtime
    assert sched.tick(late) == 0
    assert _msgs(tq, rid) == []
    r = tq("MATCH (r:Routine {id: $r}) RETURN r.nextRunAt AS n, r.lastSkippedAt IS NOT NULL AS s", r=rid)[0]
    assert r["n"].to_native() == datetime(2026, 6, 1, 14, 5, tzinfo=UTC) and r["s"]
    assert sched.skipped == 1


def test_cron_uses_the_routine_timezone(cdc, world, sched, tq):
    a = world.agent("t-a")
    rid = _routine(world, a, trigger="cron", cron="0 9 * * *", tz="Europe/Paris", deliverTo="inbox:t-a")
    sched.tick(datetime(2026, 6, 1, 5, 0, tzinfo=UTC))
    assert tq("MATCH (r:Routine {id: $r}) RETURN r.nextRunAt AS n", r=rid)[0]["n"].to_native() == datetime(2026, 6, 1, 7, 0, tzinfo=UTC)
    assert next_after("0 9 * * *", "Europe/Paris", datetime(2026, 1, 15, 5, 0, tzinfo=UTC)) == datetime(2026, 1, 15, 8, 0, tzinfo=UTC)  # hiver


def test_once_fires_then_disables_and_late_once_still_fires(cdc, world, sched, tq):
    a = world.agent("t-a")
    run_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    rid = _routine(world, a, trigger="once", runAt=run_at.isoformat(), deliverTo="inbox:t-a", payload={"body": "relance"})
    assert sched.tick(run_at - timedelta(minutes=1)) == 0
    assert sched.tick(run_at + timedelta(hours=3)) == 1                     # misfire = fire (timer default)
    assert [m["id"] for m in _msgs(tq, rid)] == [f"{rid}@2026-06-01T12:00:00Z"]
    assert tq("MATCH (r:Routine {id: $r}) RETURN r.enabled AS e, r.firedAt IS NOT NULL AS f", r=rid)[0] == {"e": False, "f": True}
    assert sched.tick(run_at + timedelta(hours=4)) == 0
    skip_id = _routine(world, a, trigger="once", runAt=run_at.isoformat(), deliverTo="inbox:t-a", misfire="skip")
    assert sched.tick(run_at + timedelta(hours=5)) == 0 and _msgs(tq, skip_id) == []


def test_can_send_to_is_checked_at_creation_and_at_each_firing(cdc, world, sched, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    body = {"trigger": "once", "runAt": "2026-06-01T12:00:00+00:00", "deliverTo": "inbox:t-b"}
    assert world.post("/routines", a, body).status_code == 403              # at creation
    world.send_to(a, "inbox:t-b")
    rid = _routine(world, a, **body)
    tq("MATCH (:Agent {id: 't-a'})-[c:CAN_SEND_TO]->(:Inbox {id: 'inbox:t-b'}) DELETE c")   # right removed in the meantime
    assert sched.tick(datetime(2026, 6, 1, 12, 0, 5, tzinfo=UTC)) == 0      # at trigger time
    assert _msgs(tq, rid) == []
    r = tq("MATCH (r:Routine {id: $r}) RETURN r.lastError AS e, r.enabled AS en", r=rid)[0]
    assert r["e"].startswith("403") and r["en"] is False


def test_routine_creation_validation(world):
    a = world.agent("t-a")
    base = {"deliverTo": "inbox:t-a"}
    assert world.post("/routines", a, {**base, "trigger": "cron", "cron": "not a cron"}).status_code == 403
    assert world.post("/routines", a, {**base, "trigger": "cron", "cron": "* * * * *", "tz": "Mars/Olympus"}).status_code == 403
    assert world.post("/routines", a, {**base, "trigger": "once"}).status_code == 403
    assert world.post("/routines", a, {**base, "trigger": "event", "listensTo": "incidents", "filter": {"field": "x", "op": "cypher"}}).status_code == 403
    assert world.post("/routines", a, {**base, "trigger": "event", "listensTo": "inconnu", "filter": {"field": "x", "op": "eq", "value": 1}}).status_code == 404
    ok = world.post("/routines", a, {**base, "trigger": "event", "listensTo": "incidents", "filter": {"field": "kind", "op": "eq", "value": "incident"}})
    assert ok.status_code == 201
    rid = ok.json()["id"]
    b = world.agent("t-b")
    assert world.post(f"/routines/{rid}/disable", b, {}).status_code == 404       # not the owner
    assert world.post(f"/routines/{rid}/disable", a, {}).status_code == 200
    assert world.post("/internal/deliver", a, {"id": "x"}).status_code == 403      # jeton sys requis


# ---------- latency and load ----------
def test_end_to_end_wake_latency_with_100ms_polling(cdc, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a)
    stop = threading.Event()
    th = threading.Thread(target=cdc.consumer.run, args=(stop,), daemon=True)
    th.start()
    woken = {}
    cdc.hub.on_wake(lambda ag, info: woken.setdefault(info["messageId"], time.perf_counter()))
    lat = []
    try:
        for _ in range(15):
            t0 = time.perf_counter()
            mid = world.send(a, sid, ["inbox:t-b"]).json()["id"]
            for _ in range(200):
                if mid in woken:
                    break
                time.sleep(0.01)
            assert mid in woken, "no wake-up"
            lat.append((woken[mid] - t0) * 1000)
            time.sleep(0.03)
    finally:
        stop.set()
        th.join(timeout=3)
    lat.sort()
    print(f"\nlatency send -> wake-up (poll 100 ms, n=15) : p50={lat[7]:.0f} ms, p95={lat[13]:.0f} ms, max={lat[-1]:.0f} ms")
    assert lat[7] < 500 and lat[-1] < 1500
    s = cdc.consumer.stats.snapshot()
    assert s["lagMs"]["p50"] is not None and s["woken"] >= 15


# ---------- WebSocket ----------
def test_websocket_streams_and_isolates_wakes(cdc, world, gw_url):
    a, b = world.agent("t-a"), world.agent("t-b")
    app = create_app(cdc.settings, autostart=False, consumer=cdc.consumer, scheduler=cdc.scheduler, hub=cdc.hub)
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"] is True
        with pytest.raises(Exception):
            with c.websocket_connect("/ws/events?token=mauvais"):
                pass
        with pytest.raises(Exception):                                          # the wake-up endpoint only accepts runtimes
            with c.websocket_connect(f"/ws/wake?token={tok('user', 'ing-qualite')['Authorization'][7:]}"):
                pass
        cdc.hub.publish({"t": "2026-01-01T00:00:00Z", "type": "sent", "actor": "x", "target": "y", "payload": {"old": True}})
        with c.websocket_connect(f"/ws/events?token={tok('user', 'ing-qualite')['Authorization'][7:]}") as ev, \
             c.websocket_connect(f"/ws/wake?token={tok('svc', a)['Authorization'][7:]}") as wk:
            assert ev.receive_json()["payload"] == {"old": True}              # recent history replayed
            assert wk.receive_json() == {"type": "hello", "agent": a}
            new = {"t": "2026-01-01T00:00:01Z", "type": "woken", "actor": a, "target": None, "payload": {}}
            cdc.hub.publish(new)
            assert ev.receive_json() == new
            cdc.hub.wake(b, {"messageId": "for-b"})
            cdc.hub.wake(a, {"messageId": "for-a"})
            assert wk.receive_json() == {"type": "wake", "messageId": "for-a"}   # never another agent's wake-up
        assert "p50" in c.get("/stats").json()["lagMs"]
