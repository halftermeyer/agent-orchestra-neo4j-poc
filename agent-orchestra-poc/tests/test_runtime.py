"""Runtimes d'agents : boucle LLM scriptée, passant par la vraie passerelle HTTP (aucun accès direct à la base)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from orchestra.runtime.agent import AgentRunner
from orchestra.runtime.auditor import AuditorRunner
from orchestra.runtime.client import AgentClient
from orchestra.runtime.settings import RuntimeSettings
from tests.conftest import KGTEST, MASTER, tok

UTC = timezone.utc


def runner(agent, gw_url, cls=AgentRunner, **kw):
    st = RuntimeSettings(gateway_url=gw_url, master_key=MASTER, **kw)
    return cls(agent, AgentClient(gw_url, st.token(agent)), st)


ALL = ["set_status", "remember", "recall", "query_kg", "send_message", "commit"]


def test_agent_session_end_to_end(world, tq, fake, gw_url):
    a = world.agent("t-a", tools=ALL, kgs=["produit"])
    b = world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    mid = world.trigger(a, chain="c-run", payload={"kind": "incident", "componentId": "PRT-0001"}, body="Fuite constatée", sender="ing-qualite")
    fake.script = [
        {"tools": [("set_status", {"text": "Je regarde la pièce"}), ("query_kg", {"kg": "produit", "template": "part_info", "params": {"partId": "PRT-0001"}})]},
        {"tools": [("remember", {"statement": "PRT-0001 est la station complète", "about": [{"db": "produit", "key": "PRT-0001", "label": "SPM-7"}]}),
                   ("send_message", {"to": ["t-b"], "performative": "request", "body": "à toi", "payload": {"kind": "x"}, "attach_memory": True})]},
        {"text": "Bilan : traité."},
    ]
    r = runner("t-a", gw_url)
    assert r.handle(mid) == "completed"
    # session ouverte sur le message, fermée, réception soldée avec ses dates
    row = tq("""MATCH (s:Session {triggerMsgId: $t})-[:TRIGGERED_BY]->(m:Message {id: $m})
                MATCH (:Inbox {id: 'inbox:t-a'})-[:HAS_DAY]->(:InboxDay)-[rc:RECEIVED]->(m)
                RETURN s.closedAt IS NOT NULL AS closed, rc.status AS st, rc.workingAt IS NOT NULL AS w, rc.completedAt IS NOT NULL AS c""",
              t=f"{mid}@t-a", m=mid)
    assert row == [{"closed": True, "st": "completed", "w": True, "c": True}]
    assert tq("MATCH (:Session {triggerMsgId: $t})-[:STATUS]->(u:StatusUpdate) RETURN u.text AS t", t=f"{mid}@t-a") == [{"t": "Je regarde la pièce"}]
    calls = tq("""MATCH (:Session {triggerMsgId: $t})-[:CALLED]->(tc:ToolCall)-[:OF]->(t:Tool) OPTIONAL MATCH (tc)-[:PRODUCED]->(p)
                  RETURN t.name AS tool, tc.status AS st, labels(p)[0] AS produced ORDER BY tc.startedAt, t.name""", t=f"{mid}@t-a")
    assert {(c["tool"], c["st"], c["produced"]) for c in calls} == {
        ("set_status", "completed", None), ("query_kg", "completed", None), ("remember", "completed", "Fact"), ("send_message", "completed", "Message")}
    # le message sort dans la chaîne du déclencheur, avec le payload et la mémoire jointe
    sent = tq("""MATCH (m:Message {from: 't-a'})<-[:RECEIVED]-(:InboxDay)<-[:HAS_DAY]-(:Inbox {id: 'inbox:t-b'})
                 RETURN m.chainId AS chain, m.inReplyTo AS re, m.payloadJson AS p, EXISTS { (m)-[:CAN_READ]->(:Memory {id: 'mem:t-a'}) } AS mem""")
    assert sent == [{"chain": "c-run", "re": mid, "p": '{"kind": "x"}', "mem": True}]
    # `db: produit` est ramené au nom de base ; le fait est rattaché à une EntityRef
    assert tq("MATCH (:Fact)-[:ABOUT]->(r:EntityRef) RETURN r.db AS db, r.key AS k") == [{"db": "kgproduit", "k": "PRT-0001"}]
    # le LLM voit le résultat de l'outil, son contexte et sa liste de destinataires
    system, contents = fake.history[1]
    assert "t-b" in system and "part_where_used" in system and "Ton mandat" in system
    first = fake.history[0][1][0]["text"]
    assert "Fuite constatée" in first and "incident" in first and "ing-qualite" in first
    assert any(c["role"] == "tool" and c["name"] == "query_kg" and c["result"]["rowCount"] == 1 for c in contents)
    assert tq("MATCH (c:Chain {id: 'c-run'}) RETURN c.tokensSpent AS t")[0]["t"] == 45          # 3 appels LLM imputés à la chaîne
    assert r.handle(mid) == "already-done" and len(fake.calls) == 3


def test_refusals_are_returned_to_the_llm_and_traced_as_failed(world, tq, fake, gw_url):
    a = world.agent("t-a", tools=ALL, kgs=[])
    mid = world.trigger(a)
    fake.script = [
        {"tools": [("send_message", {"to": ["inconnu"], "body": "x"}), ("query_kg", {"kg": "produit", "template": "part_info", "params": {"partId": "PRT-0001"}}),
                   ("cpa_simulate", {"task_id": "TSK-01", "delay_days": 2}), ("outil_imaginaire", {})]},
        {"text": "d'accord"},
    ]
    assert runner("t-a", gw_url).handle(mid) == "completed"
    results = {c["name"]: c["result"] for c in fake.history[1][1] if c["role"] == "tool"}
    assert "non autorisés" in results["send_message"]["error"]
    assert "403" in results["query_kg"]["error"]
    assert "refusé" in results["cpa_simulate"]["error"]
    assert "inconnu" in results["outil_imaginaire"]["error"]
    st = {r["t"]: r["s"] for r in tq("MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(t:Tool) RETURN t.name AS t, tc.status AS s")}
    assert st == {"send_message": "failed", "query_kg": "failed"}          # cpa_simulate : refusé avant même d'être tracé (pas de CAN_USE)


def test_llm_budget_exhaustion_fails_the_session_cleanly(world, tq, fake, gw_url, client):
    a = world.agent("t-a")
    client.post("/chains", json={"id": "c-tight", "budget": 5, "tokenBudget": 12}, headers=tok("admin"))
    mid = world.trigger(a, chain="c-tight")
    fake.script = [{"tools": [("set_status", {"text": "1"})]}, {"tools": [("set_status", {"text": "2"})]}, {"text": "n'arrive pas"}]
    assert runner("t-a", gw_url).handle(mid) == "failed"
    assert tq("""MATCH (:Inbox {id: 'inbox:t-a'})-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(:Message {id: $m}) RETURN r.status AS s, r.failedAt IS NOT NULL AS f""", m=mid) == [{"s": "failed", "f": True}]
    assert tq("MATCH (c:Chain {id: 'c-tight'}) RETURN c.status AS s")[0]["s"] == "suspended"


def test_turn_limit_stops_a_runaway_agent(world, tq, fake, gw_url):
    a = world.agent("t-a", tools=["set_status"])
    mid = world.trigger(a)
    fake.script = [{"tools": [("set_status", {"text": str(i)})]} for i in range(10)]
    assert runner("t-a", gw_url, max_turns=3).handle(mid) == "failed"
    assert len(fake.calls) == 3


def test_rule_gate_skips_the_llm_for_a_fulfilled_commitment(world, tq, fake, gw_url):
    a, b = world.agent("t-a", tools=["commit"]), world.agent("t-b")
    tq("""MATCH (a:Agent {id: 't-a'}) CREATE (a)-[:COMMITTED]->(:Commitment {id: 'cm-done', agentId: 't-a', toAgent: 't-b', status: 'fulfilled', test: true, description: 'x'})
          CREATE (a)-[:COMMITTED]->(:Commitment {id: 'cm-open', agentId: 't-a', toAgent: 't-b', status: 'open', test: true, description: 'livrer le dossier', dueAt: datetime()})""")
    r = runner("t-a", gw_url)
    m1 = world.trigger(a, payload={"kind": "commitment-due", "commitmentId": "cm-done"})
    assert r.handle(m1) == "completed" and not fake.calls                       # aucun token dépensé
    m2 = world.trigger(a, payload={"kind": "commitment-due", "commitmentId": "cm-open"}, body="Échéance")
    fake.script = [{"text": "je m'en occupe"}]
    assert r.handle(m2) == "completed" and len(fake.calls) == 1
    assert "cm-open" in fake.history[0][0]                                      # les engagements ouverts figurent dans le contexte


@pytest.fixture
def sched(cdc, tq):
    tq("MATCH (r:Routine {id: 'rt-auditeur-scan'}) SET r.enabled = false")
    return cdc.scheduler


def test_commitment_timer_wakes_the_debtor_when_due(world, tq, fake, gw_url, cdc, sched):
    a, b = world.agent("t-a", tools=["commit"]), world.agent("t-b")
    world.send_to(b, "inbox:t-a")
    m0 = world.trigger(a)
    fake.script = [{"tools": [("commit", {"to": "t-b", "description": "livrer le dossier de remplacement", "due_in_minutes": 5})]}, {"text": "ok"}]
    r = runner("t-a", gw_url)
    assert r.handle(m0) == "completed"
    cid = tq("MATCH (c:Commitment) WHERE c.agentId = 't-a' RETURN c.id AS id")[0]["id"]
    cdc.drain()
    assert [e for e in cdc.of("waiting", actor="t-a") if e["payload"].get("commitmentId") == cid]   # avatar « attend » : engagement
    # l'échéance passe : la minuterie dépose une relance dans l'inbox du débiteur
    assert sched.tick(datetime.now(UTC) + timedelta(minutes=6)) == 1
    pending = [p for p in world.c.get("/inbox/pending", headers=tok("svc", "t-a")).json()["pending"]]
    mid = next(p["messageId"] for p in pending if p["messageId"].startswith(f"rt-commit-{cid}@"))
    msg = world.c.get(f"/inbox/messages/{mid}", headers=tok("svc", "t-a")).json()
    assert msg["from"] == f"routine:rt-commit-{cid}" and msg["payload"]["kind"] == "commitment-due" and msg["payload"]["debtor"] == "t-a"
    fake.calls.clear(); fake.script = [{"text": "en retard, je m'y mets"}]
    assert r.handle(mid) == "completed" and len(fake.calls) == 1                         # engagement ouvert : le LLM est réveillé


def test_approval_wakeup_then_launch_modification(world, tq, fake, gw_url, cdc, kg_world, admin):
    w = kg_world
    boss = w.agent("t-boss", tools=[("launch_modification", "2-of-3"), "request_approval", "set_status"], kgs=["produit"])
    ps = [w.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    w.send_to(boss, "inbox:t-comite")
    r = runner("t-boss", gw_url, electorates={"launch_modification": "inbox:t-comite"})
    m1 = w.trigger(boss, chain="c-modif", body="synthèse prête")
    fake.script = [{"tools": [("request_approval", {"tool": "launch_modification", "part_id": "X1", "replacement_id": "X2", "description": "remplacer X1 par X2"})]},
                   {"text": "n'arrive pas : le tour s'arrête à la demande"}]
    assert r.handle(m1) == "input-required"                                              # A2A : l'agent attend
    assert len(fake.calls) == 1
    assert tq("MATCH (:Inbox {id: 'inbox:t-boss'})-[:HAS_DAY]->(:InboxDay)-[rc:RECEIVED]->(:Message {id: $m}) RETURN rc.status AS s, rc.inputRequiredAt IS NOT NULL AS d", m=m1) == [{"s": "input-required", "d": True}]
    ap = tq("MATCH (ap:Approval) RETURN ap.id AS id, ap.status AS s")[0]
    assert ap["s"] == "pending"
    # le comité vote : à la décision, l'agent est réveillé par un message système
    for p in ps[:2]:
        assert w.post(f"/approvals/{ap['id']}/votes", p, {"decision": "approve"}, kind="user").status_code == 201
    cdc.drain()
    dec = next(x for x in w.c.get("/inbox/pending", headers=tok("svc", "t-boss")).json()["pending"] if x["messageId"].startswith("approval:"))
    assert dec["chainId"] == "c-modif"
    fake.calls.clear()
    fake.script = [{"tools": [("launch_modification", {"approval_id": ap["id"]})]}, {"text": "modification lancée"}]
    assert r.handle(dec["messageId"]) == "completed"
    res = next(c for c in fake.history[-1][1] if c["role"] == "tool")["result"]
    assert res["versionId"] == "VER-1.1"
    assert ap["id"] in fake.history[1][1][0]["text"]                                   # le LLM voit la décision à son réveil
    with admin.session(database=KGTEST) as s:
        assert s.run("CYPHER 25 MATCH (p:Part {id: 'X1'}) RETURN p.retiredIn AS r").single()["r"] == "VER-1.1"
    st = tq("MATCH (tc:ToolCall)-[:OF]->(:Tool {name: 'launch_modification'}) RETURN tc.status AS s, tc.endedAt IS NOT NULL AS e")
    assert st == [{"s": "completed", "e": True}]
    # la modification du KG a traversé le pont : un message brut dans la chaîne de la modification (txMetadata)
    cdc.drain()
    raw = tq("MATCH (m:Message {from: 'pont-kg'}) RETURN m.chainId AS c")
    assert "c-modif" in {x["c"] for x in raw}
