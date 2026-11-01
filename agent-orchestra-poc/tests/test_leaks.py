"""Tests de non-fuite des droits (obligatoires) : un seul chemin de lecture, périmètre ReBAC."""
import time
from datetime import datetime, timezone

from tests.conftest import tok


def _two(world):
    a, b = world.agent("t-a"), world.agent("t-b")
    return a, b, world.session(a), world.session(b)


def test_peer_memory_is_invisible(client, world):
    a, b, sa, sb = _two(world)
    world.remember(a, sa, "A sait que la pompe fuit")
    world.remember(b, sb, "B garde un secret sur le joint")
    assert world.recall(a, "secret joint") == {"A sait que la pompe fuit"}
    assert world.recall(b, "pompe") == {"B garde un secret sur le joint"}
    assert world.recall(a, "secret", memoryIds=["mem:t-b"]) == set()


def test_supervisor_reads_down_never_up(client, world):
    boss, sub = world.agent("t-boss"), world.agent("t-sub")
    world.supervises(boss, sub)
    sb, ss = world.session(boss), world.session(sub)
    world.remember(boss, sb, "décision du chef")
    world.remember(sub, ss, "note du subordonné")
    assert world.recall(boss, "note décision") == {"décision du chef", "note du subordonné"}
    assert world.recall(sub, "note décision") == {"note du subordonné"}


def test_attached_memory_snapshot_is_visible_only_to_reachers(client, world):
    a, r, other = world.agent("t-a"), world.agent("t-r"), world.agent("t-o")
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "fait partagé")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot"}).status_code == 201
    assert world.recall(r, "fait") == {"fait partagé"}
    assert world.recall(other, "fait") == set()          # un pair du destinataire ne lit rien


def test_snapshot_does_not_show_later_facts_but_live_does(client, world):
    a, r, l = world.agent("t-a"), world.agent("t-r"), world.agent("t-l")
    world.send_to(a, "inbox:t-r", "inbox:t-l")
    sa = world.session(a)
    world.remember(a, sa, "avant le partage")
    time.sleep(0.05)
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot"}).status_code == 201
    until = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))
    assert world.send(a, sa, ["inbox:t-l"], attachMemory={"mode": "live", "until": until}).status_code == 201
    time.sleep(0.05)
    world.remember(a, sa, "après le partage")
    assert world.recall(r, "partage") == {"avant le partage"}               # snapshot postérieur : masqué
    assert world.recall(l, "partage") == {"avant le partage", "après le partage"}   # live : visible


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
    world.remember(a, sa, "partage périmé")
    tq("""MATCH (r:Agent {id: 't-r'})-[:HAS_INBOX]->(i:Inbox), (mem:Memory {id: 'mem:t-a'})
          MERGE (d:Day:InboxDay {inboxId: i.id, date: date()}) MERGE (i)-[:HAS_DAY]->(d)
          CREATE (m:Message {id: 'expired-share', chainId: 'c', createdAt: datetime(), from: 't-a'})
          CREATE (d)-[:RECEIVED {status: 'submitted', submittedAt: datetime()}]->(m)
          CREATE (m)-[:CAN_READ {mode: 'live', asOf: datetime(), until: datetime() - duration('PT1H'), private: false}]->(mem)""")
    assert world.recall(r, "partage périmé") == set()
    tq("MATCH ()-[g:CAN_READ]->() SET g.until = datetime() + duration('PT1H')")
    assert world.recall(r, "partage périmé") == {"partage périmé"}


def test_share_goes_up_the_recipients_hierarchy_unless_private(client, world):
    a, r, boss = world.agent("t-a"), world.agent("t-r"), world.agent("t-boss")
    world.supervises(boss, r)
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "fait remontant")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot", "private": False}).status_code == 201
    assert world.recall(boss, "fait remontant") == {"fait remontant"}
    assert world.recall(r, "fait remontant") == {"fait remontant"}


def test_private_share_does_not_go_up(client, world):
    a, r, boss = world.agent("t-a"), world.agent("t-r"), world.agent("t-boss")
    world.supervises(boss, r)
    world.send_to(a, "inbox:t-r")
    sa = world.session(a)
    world.remember(a, sa, "fait privé")
    assert world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot", "private": True}).status_code == 201
    assert world.recall(r, "fait privé") == {"fait privé"}       # le destinataire lit
    assert world.recall(boss, "fait privé") == set()             # pas son responsable


def test_no_cascade_without_can_share(client, world):
    a, r, d = world.agent("t-a"), world.agent("t-r"), world.agent("t-d")
    world.send_to(a, "inbox:t-r")
    world.send_to(r, "inbox:t-d")
    sa, sr = world.session(a), world.session(r)
    world.remember(a, sa, "fait de A")
    world.send(a, sa, ["inbox:t-r"], attachMemory={})
    assert world.recall(r, "fait de A") == {"fait de A"}
    # R tente de re-partager la mémoire de A : refusé
    assert world.send(r, sr, ["inbox:t-d"], attachMemory={"memoryId": "mem:t-a"}).status_code == 403
    assert world.recall(d, "fait de A") == set()
    # avec un droit CAN_SHARE explicite, c'est permis


def test_can_share_allows_resharing(client, world, tq):
    a, r, d = world.agent("t-a"), world.agent("t-r"), world.agent("t-d")
    world.send_to(a, "inbox:t-r")
    world.send_to(r, "inbox:t-d")
    sa, sr = world.session(a), world.session(r)
    world.remember(a, sa, "fait de A")
    tq("MATCH (r:Agent {id: 't-r'}), (m:Memory {id: 'mem:t-a'}) CREATE (r)-[:CAN_SHARE]->(m)")
    assert world.send(r, sr, ["inbox:t-d"], attachMemory={"memoryId": "mem:t-a"}).status_code == 201
    assert world.recall(d, "fait de A") == {"fait de A"}


def test_supervising_a_person_gives_no_read_access(client, world, tq):
    mgr, emp = world.agent("t-mgr", person=True), world.agent("t-emp", person=True)
    world.supervises(mgr, emp)
    emb = client.ctx.llm().embed(["note personnelle de l'employé"], 768)[0]
    tq("""MATCH (mem:Memory {id: 'mem:t-emp'})
          CREATE (mem)-[:ASSERTS]->(:Fact {id: 'f-emp', statement: $s, embedding: $e, memoryId: mem.id, confidence: 1.0,
                                           validFrom: datetime() - duration('P1D'), recordedAt: datetime() - duration('P1D'), test: true})""",
       s="note personnelle de l'employé", e=emb)
    assert world.recall(emp, "note", kind="user") == {"note personnelle de l'employé"}
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
    ok = world.post("/facts", b, {"sessionId": sb, "statement": "relais défaillant", "about": [ref]})
    assert ok.status_code == 201, ok.text
    assert tq("""MATCH (:Fact {id: $f})-[:ABOUT]->(r:Ref:EntityRef {db: 'kgproduit', key: 'PRT-0045'})-[:IN_KG]->(k:KnowledgeGraph)
                 RETURN k.id AS k, r.labelAt IS NOT NULL AS d""", f=ok.json()["id"]) == [{"k": "produit", "d": True}]
    # lecture du proxy : même contrôle
    assert world.post("/kg/resolve", a, {"db": "kgproduit", "key": "PRT-0045"}).status_code == 403
    assert world.post("/kg/resolve", b, {"db": "kgproduit", "key": "PRT-0045"}).json()["exists"] is True
    assert world.post("/kg/resolve", b, {"db": "kgprojet", "key": "TSK-01"}).status_code == 403


def test_derived_from_requires_visibility(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sa, sb = world.session(a), world.session(b)
    fa = world.remember(a, sa, "fait de A")
    r = world.post("/facts", b, {"sessionId": sb, "statement": "intégré", "derivedFrom": [fa]})
    assert r.status_code == 403                                  # A n'a rien partagé
    world.send(a, sa, ["inbox:t-b"], attachMemory={})
    r = world.post("/facts", b, {"sessionId": sb, "statement": "intégré", "derivedFrom": [fa]})
    assert r.status_code == 201, r.text
    assert tq("MATCH (:Fact {id: $n})-[:DERIVED_FROM]->(:Fact {id: $o}) RETURN count(*) AS n", n=r.json()["id"], o=fa)[0]["n"] == 1


def test_revision_closes_instead_of_overwriting(client, world, tq):
    a = world.agent("t-a")
    sa = world.session(a)
    old = world.remember(a, sa, "le seuil est de 10 bar")
    time.sleep(0.05)
    t_before = datetime.now(timezone.utc).isoformat()
    time.sleep(0.2)
    r = world.post(f"/facts/{old}/revise", a, {"sessionId": sa, "statement": "le seuil est de 12 bar"})
    assert r.status_code == 201, r.text
    assert world.post(f"/facts/{old}/revise", a, {"sessionId": sa, "statement": "encore"}).status_code == 404
    rows = tq("MATCH (n:Fact)-[:SUPERSEDES]->(o:Fact {id: $o}) RETURN o.validTo IS NOT NULL AS closed, n.validFrom = o.validTo AS contiguous", o=old)
    assert rows == [{"closed": True, "contiguous": True}]
    assert world.recall(a, "seuil") == {"le seuil est de 12 bar"}
    assert world.recall(a, "seuil", asOf=t_before) == {"le seuil est de 10 bar"}      # relecture à une date passée
    # un tiers ne peut pas réviser le fait d'autrui
    b = world.agent("t-b")
    sb = world.session(b)
    assert world.post(f"/facts/{r.json()['id']}/revise", b, {"sessionId": sb, "statement": "piraté"}).status_code == 404


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
