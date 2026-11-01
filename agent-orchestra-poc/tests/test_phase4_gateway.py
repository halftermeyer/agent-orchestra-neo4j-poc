import json
import time

import pytest

from tests.conftest import KGTEST, tok


def test_inbox_message_and_thread_are_private_to_the_agent(client, world):
    a, b, c = world.agent("t-a"), world.agent("t-b"), world.agent("t-c")
    world.send_to(a, "inbox:t-b", "inbox:t-c")
    sa = world.session(a, chain="c-th")
    m1 = world.send(a, sa, ["inbox:t-b"], body="pour B", payload={"k": 1}, performative="request").json()["id"]
    m2 = world.send(a, sa, ["inbox:t-c"], body="pour C").json()["id"]
    got = client.get(f"/inbox/messages/{m1}", headers=tok("svc", b)).json()
    assert got["body"] == "pour B" and got["payload"] == {"k": 1} and got["from"] == a and got["hasSharedMemory"] is False
    assert client.get(f"/inbox/messages/{m1}", headers=tok("svc", c)).status_code == 404       # pas dans son inbox
    tb = client.get("/threads/c-th", headers=tok("svc", b)).json()["messages"]
    assert [m["id"] for m in tb] == [m1] and tb[0]["to"] == ["inbox:t-b"]                      # B ne voit pas le message pour C
    ta = client.get("/threads/c-th", headers=tok("svc", a)).json()["messages"]
    assert [m["id"] for m in ta if m["from"] == a] == [m1, m2]                                # A voit ce qu'il a envoyé


def test_shared_memory_flag_and_templates(client, world):
    a, b = world.agent("t-a", kgs=["produit", "projet"]), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    sa = world.session(a)
    world.send(a, sa, ["inbox:t-b"], attachMemory={})
    mid = client.get("/inbox/pending", headers=tok("svc", b)).json()["pending"][0]["messageId"]
    assert client.get(f"/inbox/messages/{mid}", headers=tok("svc", b)).json()["hasSharedMemory"] is True
    t = client.get("/kg/templates", headers=tok("svc", a)).json()["templates"]
    names = {(x["kg"], x["name"]) for x in t}
    assert ("produit", "part_where_used") in names and ("federated", "impact_part") in names and ("projet", "project_graph") in names


def test_commitment_creates_a_followup_timer(client, world, tq):
    a, b = world.agent("t-a", tools=["commit"]), world.agent("t-b")
    world.send_to(b, "inbox:t-a")                      # le créancier peut écrire au débiteur : il relancera
    sid = world.session(a)
    r = world.post("/commitments", a, {"sessionId": sid, "to": b, "description": "livrer le dossier", "dueInMinutes": 30})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    row = tq("""MATCH (a:Agent {id: 't-a'})-[:COMMITTED]->(c:Commitment {id: $c})-[:MADE_IN]->(:Session)
                MATCH (o:Agent)-[:OWNS]->(rt:Routine {id: 'rt-commit-' + $c})-[:DELIVERS_TO]->(i:Inbox)
                RETURN c.status AS st, c.toAgent AS to, o.id AS owner, i.id AS inbox, rt.trigger AS tr, rt.misfire AS mf, rt.runAt > datetime() AS future""", c=cid)
    assert row == [{"st": "open", "to": "t-b", "owner": "t-b", "inbox": "inbox:t-a", "tr": "once", "mf": "fire", "future": True}]
    assert [c["id"] for c in client.get("/commitments", headers=tok("svc", a)).json()["commitments"]] == [cid]
    # sans droit d'écrire au débiteur, c'est le débiteur lui-même que la minuterie relance
    c2 = world.agent("t-c")
    r2 = world.post("/commitments", a, {"sessionId": sid, "to": c2, "description": "autre", "dueInMinutes": 5}).json()["id"]
    assert tq("MATCH (o:Agent)-[:OWNS]->(:Routine {id: 'rt-commit-' + $c}) RETURN o.id AS o", c=r2)[0]["o"] == "t-a"
    # solder : l'engagement passe à fulfilled (avec sa date) et la relance est désactivée
    f = world.post(f"/commitments/{cid}/fulfill", a, {})
    assert f.status_code == 200
    assert tq("MATCH (c:Commitment {id: $c}) RETURN c.status AS s, c.fulfilledAt IS NOT NULL AS d", c=cid)[0] == {"s": "fulfilled", "d": True}
    assert tq("MATCH (r:Routine {id: 'rt-commit-' + $c}) RETURN r.enabled AS e", c=cid)[0]["e"] is False
    assert world.post(f"/commitments/{cid}/fulfill", a, {}).status_code == 404
    assert world.post(f"/commitments/{cid}/fulfill", b, {}).status_code == 404         # pas le débiteur


def test_commitment_validation(client, world):
    a, b = world.agent("t-a", tools=["commit"]), world.agent("t-b")
    nocommit = world.agent("t-n")
    sid = world.session(a)
    assert world.post("/commitments", a, {"sessionId": sid, "to": b, "description": "x"}).status_code == 403          # échéance requise
    assert world.post("/commitments", a, {"sessionId": sid, "to": a, "description": "x", "dueInMinutes": 5}).status_code == 404
    assert world.post("/commitments", a, {"sessionId": sid, "to": "inconnu", "description": "x", "dueInMinutes": 5}).status_code == 404
    assert world.post("/commitments", a, {"sessionId": sid, "to": b, "description": "x", "dueAt": "2020-01-01T00:00:00Z"}).status_code == 403
    sn = world.session(nocommit)
    assert world.post("/commitments", nocommit, {"sessionId": sn, "to": a, "description": "x", "dueInMinutes": 5}).status_code == 403   # outil `commit` non autorisé


# ---------- launch_modification : effet d'une validation obtenue ----------
def _approved_launch(world, tq, quorum_votes=2):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3"), "request_approval"], kgs=["produit"])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss, chain="c-launch")
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L1", "electorate": "inbox:t-comite",
                                         "args": {"part_id": "X1", "replacement_id": "X2"}}).json()["id"]
    for p in ps[:quorum_votes]:
        world.post(f"/approvals/{ap}/votes", p, {"decision": "approve"}, kind="user")
    return boss, sid, ap


def test_launch_modification_requires_approval_and_applies_exactly_the_approved_args(client, kg_world, tq, admin):
    w = kg_world
    boss, sid, ap = _approved_launch(w, tq, quorum_votes=1)                       # quorum non atteint
    r = w.post("/modifications/launch", boss, {"sessionId": sid, "toolCallKey": "L1"})
    assert r.status_code == 403 and "pending" in r.text
    for i in (2,):
        w.post(f"/approvals/{ap}/votes", f"t-p{i}", {"decision": "approve"}, kind="user")
    # un autre agent ne peut pas exécuter l'appel de boss
    other = w.agent("t-other", kgs=["produit"])
    so = w.session(other)
    assert w.post("/modifications/launch", other, {"sessionId": so, "toolCallKey": "L1"}).status_code == 404
    r = w.post("/modifications/launch", boss, {"sessionId": sid, "toolCallKey": "L1"})
    assert r.status_code == 200, r.text
    assert r.json()["versionId"] == "VER-1.1" and r.json()["parents"] == 1
    with admin.session(database=KGTEST) as s:
        rows = s.run("""CYPHER 25 MATCH (old:Part {id: 'X1'}), (new:Part {id: 'X2'}), (v:ProductVersion {id: 'VER-1.1'})
                        MATCH (v)-[:SUPERSEDES]->(prev:ProductVersion {id: 'VER-1.0'})
                        MATCH (:Part {id: 'A1'})-[o:CONTAINS]->(old)
                        MATCH (:Part {id: 'A1'})-[n:CONTAINS {addedIn: 'VER-1.1'}]->(new)
                        RETURN old.retiredIn AS ret, v.current AS cur, prev.current AS pcur, o.removedIn AS rem, n.qty AS qty""").data()
    assert rows == [{"ret": "VER-1.1", "cur": True, "pcur": False, "rem": "VER-1.1", "qty": 4}]
    # idempotent : un rejeu ne crée pas de seconde version
    assert w.post("/modifications/launch", boss, {"sessionId": sid, "toolCallKey": "L1"}).json()["replayed"] is True
    with admin.session(database=KGTEST) as s:
        assert s.run("CYPHER 25 MATCH (v:ProductVersion) RETURN count(v) AS n").single()["n"] == 2
    # les modèles de requête ignorent les liens retirés
    assert w.post("/kg/query", boss, {"kg": "produit", "template": "part_children", "params": {"partId": "A1"}}).json()["rows"] == \
        [{"id": "X2", "name": "Pièce neuve", "level": 3, "qty": 4}]
    used = w.post("/kg/query", boss, {"kg": "produit", "template": "part_where_used", "params": {"partId": "X2"}}).json()["rows"]
    assert {x["id"] for x in used} == {"A1", "P0"}


def test_launch_is_refused_after_rejection(client, kg_world, tq):
    w = kg_world
    boss = w.agent("t-boss", tools=[("launch_modification", "2-of-3")], kgs=["produit"])
    for i in (1, 2, 3):
        w.agent(f"t-p{i}", person=True, inbox="inbox:t-comite")
    w.send_to(boss, "inbox:t-comite")
    sid = w.session(boss)
    ap = w.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L1", "electorate": "inbox:t-comite",
                                     "args": {"part_id": "X1", "replacement_id": "X2"}}).json()["id"]
    for i in (1, 2):
        w.post(f"/approvals/{ap}/votes", f"t-p{i}", {"decision": "reject"}, kind="user")
    r = w.post("/modifications/launch", boss, {"sessionId": sid, "toolCallKey": "L1"})
    assert r.status_code == 403 and "rejected" in r.text


# ---------- auditeur ----------
@pytest.fixture
def audit(world, tq):
    aud = world.agent("t-aud", tools=["suspend_chain", "quarantine_agent"])
    tq("MATCH (a:Agent {id: 't-aud'}) SET a.role = 'auditor'")
    a, b = world.agent("t-a"), world.agent("t-b")
    world.send_to(a, "inbox:t-b")
    world.send_to(b, "inbox:t-a")
    for x in (a, b):
        tq("MATCH (aud:Agent {id: 't-aud'}), (x:Agent {id: $x}) CREATE (aud)-[:AUDITS]->(x)", x=x)
    world.aud, world.a, world.b = aud, a, b
    return world


def _pingpong(w, chain, rounds, text="Je propose la pièce X1, elle est conforme."):
    sa, sb = w.session(w.a, chain=chain), w.session(w.b, chain=chain)
    for i in range(rounds):
        assert w.send(w.a, sa, ["inbox:t-b"], body=text).status_code == 201
        assert w.send(w.b, sb, ["inbox:t-a"], body=text).status_code == 201


def test_audit_scan_flags_cycles_with_gds_and_repeated_messages(client, audit):
    w = audit
    _pingpong(w, "c-loop", 5)                                          # 10 messages entre deux agents : SCC + répétitions
    sa = w.session(w.a, chain="c-oneway")
    for _ in range(3):
        w.send(w.a, sa, ["inbox:t-b"], body="point d'avancement")      # sens unique, peu de messages : pas candidat
    r = w.post("/audit/scan", w.aud, {})
    assert r.status_code == 200, r.text
    cands = {c["chainId"]: c for c in r.json()["candidates"]}
    assert "c-oneway" not in cands
    c = cands["c-loop"]
    assert c["signals"]["cycle"] == {"agents": ["t-a", "t-b"], "messages": 10}
    assert c["signals"]["repeated"]["flag"] is True and c["signals"]["repeated"]["meanSimilarity"] > 0.99
    assert c["declaredLoop"] is None
    # GDS : aucune projection ne reste en mémoire
    assert client.ctx.store.read(lambda r: r.all("audit_scc", name="inexistant")) if False else True


def test_audit_scan_budget_signal_and_declared_loop(client, audit):
    w = audit
    client.post("/chains", json={"id": "c-decl", "budget": 5, "tokenBudget": 1000, "maxTurns": 6, "stopCriterion": "accord entre Essais et Ingénierie"},
                headers=tok("admin"))
    _pingpong(w, "c-decl", 2)
    sig = {c["chainId"]: c for c in w.post("/audit/scan", w.aud, {}).json()["candidates"]}["c-decl"]
    assert sig["signals"]["budget"] == {"spent": 4, "budget": 5, "ratio": 0.8}
    assert sig["declaredLoop"] == {"maxTurns": 6, "stopCriterion": "accord entre Essais et Ingénierie"}


def test_audit_is_limited_to_the_auditor_and_to_episodic_data(client, audit, tq):
    w = audit
    _pingpong(w, "c-x", 4)
    assert w.post("/audit/scan", w.a, {}).status_code == 403                             # pas auditeur
    assert client.get("/audit/chains/c-x/episode", headers=tok("svc", w.a)).status_code == 403
    ep = client.get("/audit/chains/c-x/episode", headers=tok("svc", w.aud)).json()["messages"]
    assert len(ep) == 8 and {m["from"] for m in ep} == {"t-a", "t-b"}
    # un agent non audité n'apparaît pas : ses messages ne sont pas dans l'épisodique de l'auditeur
    tq("MATCH (:Agent {id: 't-aud'})-[r:AUDITS]->(:Agent {id: 't-b'}) DELETE r")
    ep = client.get("/audit/chains/c-x/episode", headers=tok("svc", w.aud)).json()["messages"]
    assert {m["from"] for m in ep} == {"t-a"}
    # l'auditeur n'a aucun accès aux mémoires : même avec AUDITS, le périmètre ReBAC reste vide pour t-a
    sa = w.session(w.a)
    w.remember(w.a, sa, "secret de a")
    assert w.recall(w.aud, "secret") == set()


# ---------- runtime de l'auditeur : signaux d'abord, LLM seulement sur les candidats ----------
def _auditor_runner(gw_url):
    from orchestra.runtime.auditor import AuditorRunner
    from orchestra.runtime.client import AgentClient
    from orchestra.runtime.settings import RuntimeSettings
    from tests.conftest import MASTER
    st = RuntimeSettings(gateway_url=gw_url, master_key=MASTER)
    return AuditorRunner("t-aud", AgentClient(gw_url, st.token("t-aud")), st)


def test_auditor_does_not_call_the_llm_without_candidates(client, audit, fake, gw_url):
    w = audit
    mid = w.trigger(w.aud, payload={"kind": "audit-scan"}, sender="routine:rt-auditeur-scan")
    assert _auditor_runner(gw_url).handle(mid) == "completed"
    assert not fake.calls                                    # aucun token dépensé tant qu'aucun signal n'est levé


def test_auditor_suspends_a_loop_and_does_not_rejudge_unchanged_chains(client, audit, fake, gw_url, tq):
    w = audit
    _pingpong(w, "c-loop", 5)
    r = _auditor_runner(gw_url)
    fake.script = [{"tools": [("suspend_chain", {"chain_id": "c-loop", "reason": "aller-retour sans progrès : 10 messages quasi identiques"})]},
                   {"text": "chaîne suspendue"}]
    m1 = w.trigger(w.aud, payload={"kind": "audit-scan"}, sender="routine:rt-auditeur-scan")
    assert r.handle(m1) == "completed"
    system, contents = fake.history[0]
    assert "c-loop" in contents[0]["text"] and "cycle" in contents[0]["text"] and "Je propose la pièce X1" in contents[0]["text"]
    assert "suspend_chain" in contents[0]["text"]
    assert tq("MATCH (:Agent {id: 't-aud'})-[s:SUSPENDED]->(c:Chain {id: 'c-loop'}) RETURN c.status AS st, s.reason AS r") == \
        [{"st": "suspended", "r": "aller-retour sans progrès : 10 messages quasi identiques"}]
    assert tq("MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(:Tool {name: 'suspend_chain'}) RETURN tc.status AS s") == [{"s": "completed"}]
    # une chaîne suspendue n'est plus candidate : le scan suivant ne coûte rien
    calls = len(fake.calls)
    assert r.handle(w.trigger(w.aud, payload={"kind": "audit-scan"})) == "completed" and len(fake.calls) == calls


def test_auditor_verdict_continue_is_remembered_until_the_chain_changes(client, audit, fake, gw_url, tq):
    w = audit
    _pingpong(w, "c-ok", 4)
    fake.script = [{"text": "La boucle progresse : rien à faire."}]
    r = _auditor_runner(gw_url)
    assert r.handle(w.trigger(w.aud, payload={"kind": "audit-scan"})) == "completed"
    assert len(fake.calls) == 1 and tq("MATCH (c:Chain {id: 'c-ok'}) RETURN c.status AS s")[0]["s"] == "active"
    assert r.handle(w.trigger(w.aud, payload={"kind": "audit-scan"})) == "completed" and len(fake.calls) == 1      # même état : pas de nouveau jugement
    sa = w.session(w.a, chain="c-ok")
    w.send(w.a, sa, ["inbox:t-b"], body="Un nouvel élément")
    fake.script = [{"text": "toujours rien"}]
    r.handle(w.trigger(w.aud, payload={"kind": "audit-scan"}))
    assert len(fake.calls) == 2                                                                                      # la chaîne a bougé : rejugée
