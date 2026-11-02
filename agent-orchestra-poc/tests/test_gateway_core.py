import json

from neo4j import GraphDatabase

from orchestra import config
from tests.conftest import tok


def test_auth_rules(client, world):
    a = world.agent("t-a")
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer nope.nope"}).status_code == 401
    assert client.get("/me", headers=tok("svc", "inconnu")).status_code == 401
    # jeton « user » sur un agent logiciel, et inversement : refusés
    assert client.get("/me", headers=tok("user", a)).status_code == 401
    assert client.get("/me", headers=tok("svc", "chef-projet")).status_code == 401
    assert client.get("/me", headers=tok("admin")).status_code == 403
    me = client.get("/me", headers=tok("svc", a)).json()
    assert me["id"] == a and me["version"]["model"] == "fake-model"


def test_agent_id_never_comes_from_the_body(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a)
    r = world.post("/messages", a, {"to": ["inbox:t-b"], "performative": "inform", "body": "x", "sessionId": sid, "agentId": b})
    assert r.status_code == 422
    r = world.post("/messages", a, {"to": ["inbox:t-b"], "performative": "inform", "body": "x", "sessionId": sid, "from": b})
    assert r.status_code == 422


def test_send_message_structure(client, world, tq):
    a, b, c = world.agent("t-a"), world.agent("t-b"), world.agent("t-c")
    world.send_to(a, "inbox:t-b", "inbox:t-c")
    sid = world.session(a)
    r = world.send(a, sid, ["inbox:t-b", "inbox:t-c"], body="bonjour")
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    rows = tq("""MATCH (:Session {id: $s})-[:SENT]->(m:Message {id: $m})-[:IN_CHAIN]->(ch:Chain)
                 MATCH (i:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m)
                 RETURN m.from AS f, ch.spent AS spent, collect(i.id) AS inboxes, r.status AS st, r.submittedAt IS NOT NULL AS dated""",
              s=sid, m=mid)
    assert rows[0]["f"] == a and rows[0]["spent"] == 2 and set(rows[0]["inboxes"]) == {"inbox:t-b", "inbox:t-c"}
    assert rows[0]["st"] == "submitted" and rows[0]["dated"]
    # idempotent par id : pas de double envoi ni de double débit
    r1 = world.send(a, sid, ["inbox:t-b"], id="fixed-id-1")
    r2 = world.send(a, sid, ["inbox:t-b"], id="fixed-id-1")
    assert r1.status_code == 201 and r2.json()["duplicate"] is True
    assert tq("MATCH (m:Message {id: 'fixed-id-1'}) RETURN count(m) AS n")[0]["n"] == 1
    assert tq("MATCH (c:Chain) WHERE c.id = $c RETURN c.spent AS s", c=r.json()["chainId"])[0]["s"] == 3


def test_can_send_to_is_enforced(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    sid = world.session(a)
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 403
    assert world.send(a, sid, ["inbox:inexistante"]).status_code == 403


def test_session_chain_is_fixed(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a, chain="chain-a")
    assert world.send(a, sid, ["inbox:t-b"], chainId="autre").status_code == 403
    assert world.send(a, sid, ["inbox:t-b"], chainId="chain-a").json()["chainId"] == "chain-a"


def test_sessions_idempotent_and_owned(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    mid = world.trigger(a)
    s1 = client.post("/sessions", json={"messageId": mid}, headers=tok("svc", a)).json()
    s2 = client.post("/sessions", json={"messageId": mid}, headers=tok("svc", a)).json()
    assert s1["id"] == s2["id"]
    assert tq("MATCH (s:Session) WHERE s.agentId = $a RETURN count(s) AS n", a=a)[0]["n"] == 1
    assert tq("MATCH (:WorkDay)-[o:OPENED]->(:Session {id: $s}) RETURN count(o) AS n", s=s1["id"])[0]["n"] == 1
    assert tq("MATCH (:Session {id: $s})-[:RAN_AS]->(:AgentVersion) RETURN count(*) AS n", s=s1["id"])[0]["n"] == 1
    st = tq("MATCH (:Message {id: $m})<-[r:RECEIVED]-() RETURN r.status AS s, r.workingAt IS NOT NULL AS w", m=mid)[0]
    assert st == {"s": "working", "w": True}
    # un message qui n'est pas dans l'inbox de l'agent ne peut pas le réveiller
    assert client.post("/sessions", json={"messageId": mid}, headers=tok("svc", b)).status_code == 403
    # la session d'un autre agent est invisible
    assert client.post("/status", json={"sessionId": s1["id"], "text": "x"}, headers=tok("svc", b)).status_code == 404
    # fermeture : dates conservées, statut A2A
    assert client.post(f"/sessions/{s1['id']}/close", json={"status": "completed"}, headers=tok("svc", a)).status_code == 200
    st = tq("MATCH (:Message {id: $m})<-[r:RECEIVED]-() RETURN r.status AS s, r.completedAt IS NOT NULL AS c, r.workingAt IS NOT NULL AS w", m=mid)[0]
    assert st == {"s": "completed", "c": True, "w": True}
    assert client.post("/status", json={"sessionId": s1["id"], "text": "x"}, headers=tok("svc", a)).status_code == 409


def test_set_status(client, world, tq):
    a = world.agent("t-a")
    sid = world.session(a)
    assert world.post("/status", a, {"sessionId": sid, "text": "J'analyse l'incident"}).status_code == 200
    assert tq("MATCH (:Session {id: $s})-[:STATUS]->(u:StatusUpdate) RETURN u.text AS t, u.at IS NOT NULL AS d", s=sid) == [{"t": "J'analyse l'incident", "d": True}]


def test_agent_without_mandate_can_only_query_its_supervisor(client, world):
    boss, newbie, other = world.agent("t-boss"), world.agent("t-new", mandate=False), world.agent("t-other")
    world.supervises(boss, newbie)
    world.send_to(newbie, "inbox:t-boss", "inbox:t-other")
    sid = world.session(newbie)
    assert world.send(newbie, sid, ["inbox:t-boss"], perf="inform").status_code == 403
    assert world.send(newbie, sid, ["inbox:t-other"], perf="query").status_code == 403
    assert world.send(newbie, sid, ["inbox:t-boss"], perf="query").status_code == 201


def test_chain_budget_suspension_and_resume(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    assert client.post("/chains", json={"id": "c-budget", "budget": 2, "tokenBudget": 1000, "maxTurns": 2, "stopCriterion": "accord"},
                       headers=tok("admin")).status_code == 201
    sid = world.session(a, chain="c-budget")
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201
    r = world.send(a, sid, ["inbox:t-b"])
    assert r.status_code == 429, r.text
    ch = client.get("/chains/c-budget", headers=tok("admin")).json()
    assert ch["status"] == "suspended" and ch["spent"] == 2 and ch["suspendReason"] == "budget"
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 409
    assert tq("MATCH (m:Message {from: 't-a'})-[:IN_CHAIN]->(:Chain {id: 'c-budget'}) RETURN count(m) AS n")[0]["n"] == 2
    # la reprise est une décision humaine
    assert world.post("/chains/c-budget/resume", a, {"extraBudget": 3}).status_code == 403
    assert client.post("/chains/c-budget/resume", json={"extraBudget": 3}, headers=tok("admin")).status_code == 200
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201
    assert tq("MATCH (c:Chain {id: 'c-budget'}) RETURN c.suspendedAt IS NOT NULL AS s, c.resumedAt IS NOT NULL AS r")[0] == {"s": True, "r": True}


def test_default_budget_applies_to_new_chain(client, world, tq):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a, chain="c-default")
    world.send(a, sid, ["inbox:t-b"])
    assert tq("MATCH (c:Chain {id: 'c-default'}) RETURN c.budget AS b, c.status AS s")[0] == {"b": 50, "s": "active"}


def test_human_message_opens_direct_session(client, world, tq):
    p, b = world.agent("t-p", person=True), world.agent("t-b")
    world.send_to(p, "inbox:t-b")
    r = client.post("/messages", json={"to": ["inbox:t-b"], "performative": "request", "body": "go"}, headers=tok("user", p))
    assert r.status_code == 201, r.text
    assert tq("MATCH (:Workspace {id: 'ws:t-p'})-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(s:Session)-[:SENT]->(m:Message {id: $m}) RETURN count(m) AS n",
              m=r.json()["id"])[0]["n"] == 1
    # la session directe est close : la personne n'apparaît pas « occupée » sur la scène
    assert tq("MATCH (s:Session)-[:SENT]->(:Message {id: $m}) RETURN s.closedAt IS NOT NULL AS closed", m=r.json()["id"]) == [{"closed": True}]


def test_tx_metadata_is_recorded_in_cdc(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sid = world.session(a, chain="chain-meta")
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.CDC_USER, config.CDC_PASSWORD)) as d:
        with d.session(database="orchestratest") as s:
            before = s.run("CALL db.cdc.current() YIELD id RETURN id").single()["id"]
            mid = world.send(a, sid, ["inbox:t-b"]).json()["id"]
            rows = s.run("CALL db.cdc.query($c, [{select: 'n', labels: ['Message']}]) YIELD metadata, event RETURN metadata, event", c=before).data()
    mine = [r for r in rows if r["event"]["state"]["after"]["properties"].get("id") == mid]
    assert mine, "événement CDC introuvable"
    flat = json.dumps(mine[0]["metadata"], default=str)
    assert a in flat and "chain-meta" in flat, flat


def test_tool_calls_are_traced_and_idempotent(client, world, tq):
    a, b = world.agent("t-a", tools=["query_kg"]), world.agent("t-b")
    sid = world.session(a)
    body = {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "k1", "args": {"x": 1}}
    r1 = world.post("/tools/calls", a, body)
    r2 = world.post("/tools/calls", a, body)
    assert r1.status_code == 201 and r1.json()["status"] == "working"
    assert r2.json()["replayed"] is True
    assert tq("MATCH (tc:ToolCall) WHERE tc.agentId = $a RETURN count(tc) AS n", a=a)[0]["n"] == 1
    assert tq("MATCH (:Session {id: $s})-[:CALLED]->(tc:ToolCall)-[:OF]->(:Tool {name: 'query_kg'}) RETURN tc.startedAt IS NOT NULL AS d", s=sid)[0]["d"]
    e = world.post("/tools/calls/k1/end", a, {"status": "completed", "tokens": 12})
    assert e.status_code == 200 and e.json()["status"] == "completed"
    assert world.post("/tools/calls/k1/end", a, {"status": "failed"}).json()["replayed"] is True
    assert tq("MATCH (tc:ToolCall) WHERE tc.agentId = $a RETURN tc.status AS s, tc.tokens AS t, tc.endedAt IS NOT NULL AS e", a=a)[0] == {"s": "completed", "t": 12, "e": True}
    # outil non autorisé : le droit n'est pas hérité de la supervision
    world.supervises(a, b)
    sb = world.session(b)
    assert world.post("/tools/calls", b, {"sessionId": sb, "tool": "query_kg", "idempotencyKey": "k2"}).status_code == 403


def test_irreversible_goes_through_approval_quorum(client, world, tq):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    p1, p2, p3, p4 = (world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite" if i < 4 else "inbox:t-out") for i in range(1, 5))
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss)
    assert world.post("/tools/calls", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "x"}).status_code == 403
    req = {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "launch1", "electorate": "inbox:t-comite"}
    r = world.post("/approvals", boss, req)
    assert r.status_code == 201, r.text
    ap = r.json()["id"]
    assert world.post("/approvals", boss, req).json()["replayed"] is True
    assert tq("MATCH (tc:ToolCall {idempotencyKey: 't-boss:launch1'}) RETURN tc.status AS s")[0]["s"] == "input-required"
    # un agent logiciel ne vote pas ; un non-électeur non plus
    assert world.post(f"/approvals/{ap}/votes", boss, {"decision": "approve"}).status_code == 403
    outsider = world.agent("t-out", person=True, inbox="inbox:t-out")
    assert world.post(f"/approvals/{ap}/votes", outsider, {"decision": "approve"}, kind="user").status_code == 403
    v = lambda who, d: world.post(f"/approvals/{ap}/votes", who, {"decision": d, "comment": "ok"}, kind="user")
    assert v(p1, "approve").json()["status"] == "pending"
    assert v(p1, "approve").status_code == 409
    done = v(p2, "approve")
    assert done.status_code == 201 and done.json()["status"] == "approved" and done.json()["toolCallStatus"] == "working"
    assert v(p3, "approve").status_code == 409
    assert tq("MATCH (ap:Approval {id: $a}) RETURN ap.decidedAt IS NOT NULL AS d", a=ap)[0]["d"]
    assert tq("MATCH (:Agent:Person)-[v:VOTED]->(:Approval {id: $a}) RETURN count(v) AS n", a=ap)[0]["n"] == 2
    end = world.post("/tools/calls/launch1/end", boss, {"status": "completed"})
    assert end.status_code == 200 and end.json()["status"] == "completed"


def test_approval_rejection_and_delegation(client, world, tq):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    p1, p2, p3 = (world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in range(1, 4))
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss)
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "k", "electorate": "inbox:t-comite"}).json()["id"]
    sub = world.agent("t-sub", person=True, inbox="inbox:t-sub")
    tq("MATCH (d:Agent {id: 't-sub'}), (m:Agent {id: 't-p3'}) CREATE (d)-[:ACTS_FOR {scope: 'all', until: datetime() + duration('P1D')}]->(m)")
    vote = lambda who, d: world.post(f"/approvals/{ap}/votes", who, {"decision": d}, kind="user")
    assert vote(sub, "reject").status_code == 201          # délégué de p3
    assert vote(p3, "reject").status_code == 409           # la voix de p3 est déjà exprimée
    out = vote(p1, "reject")
    assert out.json()["status"] == "rejected" and out.json()["toolCallStatus"] == "canceled"
    assert tq("MATCH (:Agent)-[v:VOTED]->(:Approval {id: $a}) WHERE v.onBehalfOf = 't-p3' RETURN count(v) AS n", a=ap)[0]["n"] == 1


def test_approval_needs_big_enough_electorate(client, world):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    world.agent("t-p1", person=True, inbox="inbox:t-small")
    world.send_to(boss, "inbox:t-small")
    sid = world.session(boss)
    r = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "k", "electorate": "inbox:t-small"})
    assert r.status_code == 409
    r = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "k", "electorate": "inbox:autre"})
    assert r.status_code == 403


def test_auditor_powers_are_limited(client, world, tq):
    aud = world.agent("t-aud", tools=["suspend_chain", "quarantine_agent"])
    tq("MATCH (a:Agent {id: 't-aud'}) SET a.role = 'auditor'")
    x, y = world.agent("t-x"), world.agent("t-y")
    world.send_to(x, "inbox:t-y")
    sx = world.session(x, chain="c-loop")
    world.send(x, sx, ["inbox:t-y"])
    assert world.post("/chains/c-loop/suspend", x, {"reason": "non"}).status_code == 403
    r = world.post("/chains/c-loop/suspend", aud, {"reason": "aller-retour sans fin"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert tq("MATCH (:Agent {id: 't-aud'})-[s:SUSPENDED]->(:Chain {id: 'c-loop'}) RETURN s.reason AS r, s.at IS NOT NULL AS d")[0] == {"r": "aller-retour sans fin", "d": True}
    assert world.send(x, sx, ["inbox:t-y"]).status_code == 409
    # quarantaine : l'agent est bloqué, seule une personne lève
    assert world.post("/agents/t-y/quarantine", x, {"reason": "x"}).status_code == 403
    assert world.post("/agents/t-aud/quarantine", aud, {"reason": "soi-même"}).status_code == 403
    assert world.post("/agents/t-y/quarantine", aud, {"reason": "boucle"}).status_code == 200
    assert client.get("/me", headers=tok("svc", "t-y")).status_code == 403
    assert world.post("/agents/t-y/release", aud, {}).status_code == 403
    assert client.post("/agents/t-y/release", headers=tok("admin")).status_code == 200
    assert client.get("/me", headers=tok("svc", "t-y")).status_code == 200


def test_supervises_admin_operation(client, world):
    a, b, c = world.agent("t-a"), world.agent("t-b"), world.agent("t-c")
    h = tok("admin")
    s = lambda x, y, hh=h: client.post("/admin/supervises", json={"supervisor": x, "subordinate": y}, headers=hh)
    assert s(a, b).status_code == 201 and s(b, c).status_code == 201
    assert s(c, a).status_code == 409                         # cycle refusé à l'écriture
    assert s(a, a).status_code == 409
    assert s(a, b).status_code == 201                         # idempotent
    assert s(a, b, tok("svc", a)).status_code == 403          # opération privilégiée
    h1 = world.agent("t-h", person=True)
    assert s(a, h1).status_code == 403                        # un agent logiciel ne supervise pas un humain


def test_agent_versions_are_new_nodes(client, world, tq):
    a = world.agent("t-a")
    r = client.post("/admin/agents/t-a/versions", json={"model": "fake-model-b"}, headers=tok("admin"))
    assert r.status_code == 201 and r.json()["supersedes"] == "t-a@v1"
    rows = tq("MATCH (:Agent {id: 't-a'})-[:CURRENT]->(v)-[:SUPERSEDES]->(o) RETURN v.model AS m, o.model AS om, v.createdAt IS NOT NULL AS d")
    assert rows == [{"m": "fake-model-b", "om": "fake-model", "d": True}]
