"""Rights non-leak tests (mandatory): a single read path, ReBAC scope."""
import time
from datetime import datetime, timezone

from tests.conftest import tok


def _two(world):
    a, b = world.agent("t-a"), world.agent("t-b")
    return a, b, world.session(a), world.session(b)


def test_peer_memory_is_invisible(client, world):
    a, b, sa, sb = _two(world)
    world.remember(a, sa, "A knows the pump leaks")
    world.remember(b, sb, "B keeps a secret about the gasket")
    assert world.recall(a, "secret gasket") == {"A knows the pump leaks"}
    assert world.recall(b, "pump") == {"B keeps a secret about the gasket"}
    assert world.recall(a, "secret", memoryIds=["mem:t-b"]) == set()


def test_supervisor_reads_down_never_up(client, world):
    boss, sub = world.agent("t-boss"), world.agent("t-sub")
    world.supervises(boss, sub)
    sb, ss = world.session(boss), world.session(sub)
    world.remember(boss, sb, "boss's decision")
    world.remember(sub, ss, "subordinate's note")
    assert world.recall(boss, "note decision") == {"boss's decision", "subordinate's note"}
    assert world.recall(sub, "note decision") == {"subordinate's note"}


def test_attached_memory_snapshot_is_visible_only_to_reachers(client, world):
    a, r, other = world.agent("t-a"), world.agent("t-r"), world.agent("t-o")
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "shared fact")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot"}).status_code == 201
    assert world.recall(r, "fact") == {"shared fact"}
    assert world.recall(other, "fact") == set()          # a peer of the recipient reads nothing


def test_snapshot_does_not_show_later_facts_but_live_does(client, world):
    a, r, l = world.agent("t-a"), world.agent("t-r"), world.agent("t-l")
    world.send_to(a, "inbox:t-r", "inbox:t-l")
    sa = world.session(a)
    world.remember(a, sa, "before the sharing")
    time.sleep(0.05)
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot"}).status_code == 201
    until = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))
    assert world.send(a, sa, ["inbox:t-l"], attachMemory={"mode": "live", "until": until}).status_code == 201
    time.sleep(0.05)
    world.remember(a, sa, "after the sharing")
    assert world.recall(r, "sharing") == {"before the sharing"}               # later snapshot: hidden
    assert world.recall(l, "sharing") == {"before the sharing", "after the sharing"}   # live: visible


def test_live_share_must_expire(client, world):
    a, r = world.agent("t-a"), world.agent("t-r")
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "live"}).status_code == 403
    past = "2020-01-01T00:00:00+00:00"
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "live", "until": past}).status_code == 403
    far = "2999-01-01T00:00:00+00:00"
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "live", "until": far}).status_code == 403


def test_expired_share_is_invisible(client, world, tq):
    a, r = world.agent("t-a"), world.agent("t-r")
    sa = world.session(a)
    world.remember(a, sa, "stale sharing")
    tq("""MATCH (r:Agent {id: 't-r'})-[:HAS_INBOX]->(i:Inbox), (mem:Memory {id: 'mem:t-a'})
          MERGE (d:Day:InboxDay {inboxId: i.id, date: date()}) MERGE (i)-[:HAS_DAY]->(d)
          CREATE (m:Message {id: 'expired-share', chainId: 'c', createdAt: datetime(), from: 't-a'})
          CREATE (d)-[:RECEIVED {status: 'submitted', submittedAt: datetime()}]->(m)
          CREATE (m)-[:CAN_READ {mode: 'live', asOf: datetime(), until: datetime() - duration('PT1H'), private: false}]->(mem)""")
    assert world.recall(r, "stale sharing") == set()
    tq("MATCH ()-[g:CAN_READ]->() SET g.until = datetime() + duration('PT1H')")
    assert world.recall(r, "stale sharing") == {"stale sharing"}


def test_share_goes_up_the_recipients_hierarchy_unless_private(client, world):
    a, r, boss = world.agent("t-a"), world.agent("t-r"), world.agent("t-boss")
    world.supervises(boss, r)
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "upward fact")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot", "private": False}).status_code == 201
    assert world.recall(boss, "upward fact") == {"upward fact"}
    assert world.recall(r, "upward fact") == {"upward fact"}


def test_private_share_does_not_go_up(client, world):
    a, r, boss = world.agent("t-a"), world.agent("t-r"), world.agent("t-boss")
    world.supervises(boss, r)
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "private fact")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot", "private": True}).status_code == 201
    assert world.recall(r, "private fact") == {"private fact"}       # the recipient reads
    assert world.recall(boss, "private fact") == set()             # not its manager


def test_no_cascade_without_can_share(client, world):
    a, r, d = world.agent("t-a"), world.agent("t-r"), world.agent("t-d")
    world.send_to(a, "inbox:t-r")
    world.send_to(r, "inbox:t-d")
    sa, sr = world.session(a), world.session(r)
    world.remember(a, sa, "fact of A")
    world.send(a, sa, ["inbox:t-r"], attachMemory={})
    assert world.recall(r, "fact of A") == {"fact of A"}
    # R tries to re-share A's memory: refused
    assert world.send(r, sr, ["inbox:t-d"], attachMemory={"memoryId": "mem:t-a"}).status_code == 403
    assert world.recall(d, "fact of A") == set()
    # with an explicit CAN_SHARE right, it is allowed


def test_can_share_allows_resharing(client, world, tq):
    a, r, d = world.agent("t-a"), world.agent("t-r"), world.agent("t-d")
    world.send_to(a, "inbox:t-r")
    world.send_to(r, "inbox:t-d")
    sa, sr = world.session(a), world.session(r)
    world.remember(a, sa, "fact of A")
    tq("MATCH (r:Agent {id: 't-r'}), (m:Memory {id: 'mem:t-a'}) CREATE (r)-[:CAN_SHARE]->(m)")
    assert world.send(r, sr, ["inbox:t-d"], attachMemory={"memoryId": "mem:t-a"}).status_code == 201
    assert world.recall(d, "fact of A") == {"fact of A"}


def test_supervising_a_person_gives_no_read_access(client, world, tq):
    mgr, emp = world.agent("t-mgr", person=True), world.agent("t-emp", person=True)
    world.supervises(mgr, emp)
    emb = client.ctx.llm().embed(["employee's personal note"], 768)[0]
    tq("""MATCH (mem:Memory {id: 'mem:t-emp'})
          CREATE (mem)-[:ASSERTS]->(:Fact {id: 'f-emp', statement: $s, embedding: $e, memoryId: mem.id, confidence: 1.0,
                                           validFrom: datetime() - duration('P1D'), recordedAt: datetime() - duration('P1D'), test: true})""",
       s="employee's personal note", e=emb)
    assert world.recall(emp, "note", kind="user") == {"employee's personal note"}
    assert world.recall(mgr, "note", kind="user") == set()
    sc = client.get("/scope", headers=tok("user", mgr)).json()["scopes"]
    assert {s["id"] for s in sc} == {"mem:t-mgr"}


def test_software_agent_cannot_supervise_a_person(client, world):
    sw, h = world.agent("t-sw"), world.agent("t-h", person=True)
    r = client.post("/admin/supervises", json={"supervisor": sw, "subordinate": h}, headers=tok("admin"))
    assert r.status_code == 403


def test_entity_refs_require_kg_rights(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b", kgs=["produit"])
    sa, sb = world.session(a), world.session(b)
    ref = {"db": "kgproduit", "key": "PRT-0045", "label": "Relais"}
    assert world.post("/facts", a, {"sessionId": sa, "statement": "x", "about": [ref]}).status_code == 403
    ok = world.post("/facts", b, {"sessionId": sb, "statement": "faulty relay", "about": [ref]})
    assert ok.status_code == 201, ok.text
    assert tq("""MATCH (:Fact {id: $f})-[:ABOUT]->(r:Ref:EntityRef {db: 'kgproduit', key: 'PRT-0045'})-[:IN_KG]->(k:KnowledgeGraph)
                 RETURN k.id AS k, r.labelAt IS NOT NULL AS d""", f=ok.json()["id"]) == [{"k": "produit", "d": True}]
    # proxy read: same check
    assert world.post("/kg/resolve", a, {"db": "kgproduit", "key": "PRT-0045"}).status_code == 403
    assert world.post("/kg/resolve", b, {"db": "kgproduit", "key": "PRT-0045"}).json()["exists"] is True
    assert world.post("/kg/resolve", b, {"db": "kgprojet", "key": "TSK-01"}).status_code == 403


def test_derived_from_requires_visibility(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sa, sb = world.session(a), world.session(b)
    fa = world.remember(a, sa, "fact of A")
    r = world.post("/facts", b, {"sessionId": sb, "statement": "integrated", "derivedFrom": [fa]})
    assert r.status_code == 403                                  # A shared nothing
    world.send(a, sa, ["inbox:t-b"], attachMemory={})
    r = world.post("/facts", b, {"sessionId": sb, "statement": "integrated", "derivedFrom": [fa]})
    assert r.status_code == 201, r.text
    assert tq("MATCH (:Fact {id: $n})-[:DERIVED_FROM]->(:Fact {id: $o}) RETURN count(*) AS n", n=r.json()["id"], o=fa)[0]["n"] == 1


def test_revision_closes_instead_of_overwriting(client, world, tq):
    a = world.agent("t-a")
    sa = world.session(a)
    old = world.remember(a, sa, "the threshold is 10 bar")
    time.sleep(0.05)
    t_before = datetime.now(timezone.utc).isoformat()
    time.sleep(0.2)
    r = world.post(f"/facts/{old}/revise", a, {"sessionId": sa, "statement": "the threshold is 12 bar"})
    assert r.status_code == 201, r.text
    assert world.post(f"/facts/{old}/revise", a, {"sessionId": sa, "statement": "encore"}).status_code == 404
    rows = tq("MATCH (n:Fact)-[:SUPERSEDES]->(o:Fact {id: $o}) RETURN o.validTo IS NOT NULL AS closed, n.validFrom = o.validTo AS contiguous", o=old)
    assert rows == [{"closed": True, "contiguous": True}]
    assert world.recall(a, "threshold") == {"the threshold is 12 bar"}
    assert world.recall(a, "threshold", asOf=t_before) == {"the threshold is 10 bar"}      # replay at a past date
    # a third party cannot revise someone else's fact
    b = world.agent("t-b")
    sb = world.session(b)
    assert world.post(f"/facts/{r.json()['id']}/revise", b, {"sessionId": sb, "statement": "hacked"}).status_code == 404


def test_reads_are_journaled_in_the_graph(client, world, tq):
    a = world.agent("t-a", kgs=["produit"])
    sa = world.session(a)
    world.remember(a, sa, "quelque chose")
    world.recall(a, "quelque")
    world.post("/kg/query", a, {"kg": "produit", "template": "part_info", "params": {"partId": "PRT-0001"}})
    b = world.agent("t-b")
    world.post("/kg/query", b, {"kg": "produit", "template": "part_info", "params": {"partId": "PRT-0001"}})
    rows = tq("MATCH (l:AccessLog) RETURN l.agentId AS a, l.kind AS k, l.granted AS g ORDER BY a, k")
    assert {"a": "t-a", "k": "recall", "g": True} in rows
    assert {"a": "t-a", "k": "kg.query", "g": True} in rows
    assert {"a": "t-b", "k": "kg.query", "g": False} in rows
