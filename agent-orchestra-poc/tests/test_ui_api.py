import json

import pytest

from orchestra.gateway.app import create_app
from orchestra.gateway.settings import Settings
from starlette.testclient import TestClient
from tests.conftest import MASTER, tok


def login(client, who):
    r = client.post("/demo/login", json={"userId": who})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_demo_login_lists_persons_and_issues_working_tokens(client):
    users = client.get("/demo/users").json()["users"]
    assert {u["id"] for u in users} == {"ing-qualite", "comite-1", "comite-2", "comite-3", "chef-projet", "admin"}
    h = login(client, "chef-projet")
    assert client.get("/me", headers=h).json()["id"] == "chef-projet"
    assert client.get("/settings/models", headers=h).status_code == 403                  # a person is not an administrator
    assert client.get("/settings/models", headers=login(client, "admin")).status_code == 200
    assert client.post("/demo/login", json={"userId": "inconnu"}).status_code == 404
    assert client.post("/demo/login", json={"userId": "coordinateur"}).status_code == 404   # no software agent: only people
    assert client.post("/demo/login", json={"userId": "admin", "role": "x"}).status_code == 422


def test_demo_login_is_off_by_default(testdb, tmp_path):
    from orchestra import config
    st = Settings(db=testdb, master_key=MASTER, data_dir=tmp_path, neo4j_uri=config.NEO4J_URI, neo4j_password=config.GATEWAY_PASSWORD)
    assert st.demo_login is False
    with TestClient(create_app(st)) as c:
        assert c.get("/demo/users").status_code == 404
        assert c.post("/demo/login", json={"userId": "admin"}).status_code == 404


def test_ui_endpoints_reject_agents_and_anonymous(client, world):
    a = world.agent("t-a")
    for path in ("/graph/topology", "/graph/state", "/graph/agent/qualite", "/graph/rights/qualite", "/timeline"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=tok("svc", a)).status_code == 403
        assert client.get(path, headers=login(client, "admin")).status_code == 200


def test_prepared_incidents(client):
    inc = client.get("/demo/incidents", headers=login(client, "ing-qualite")).json()["incidents"]
    assert len(inc) == 10 and {"id", "componentId", "severity", "description"} <= set(inc[0])


def test_chat_shows_only_my_inbox_and_my_messages(client, world):
    a, p1, p2 = world.agent("t-a"), world.agent("t-p1", person=True), world.agent("t-p2", person=True)
    world.send_to(a, "inbox:t-p1", "inbox:t-p2")
    world.send_to(p1, "inbox:t-a")
    sa = world.session(a, chain="c-chat")
    m1 = world.send(a, sa, ["inbox:t-p1"], body="for p1", attachMemory={}).json()["id"]
    world.send(a, sa, ["inbox:t-p2"], body="for p2")
    out = client.post("/messages", json={"to": ["inbox:t-a"], "performative": "request", "body": "reply from p1", "chainId": "c-chat"},
                      headers=tok("user", p1)).json()["id"]
    msgs = client.get("/chat/messages", headers=tok("user", p1)).json()["messages"]
    mine = [(m["id"], m["direction"]) for m in msgs if m["from"] in (a, p1)]
    assert (m1, "in") in mine and (out, "out") in mine and len(mine) == 2             # the message for p2 does not appear
    first = next(m for m in msgs if m["id"] == m1)
    assert first["to"] == ["inbox:t-p1"] and first["hasSharedMemory"] is True and first["body"] == "for p1"
    assert [m["createdAt"] for m in msgs] == sorted(m["createdAt"] for m in msgs)       # ordre chronologique
    assert all(m["body"] != "for p2" for m in client.get("/chat/messages", headers=tok("user", p1)).json()["messages"])
    assert client.get("/chat/messages", headers=login(client, "admin")).status_code == 403   # the administrator has no inbox


def test_pending_approvals_are_listed_for_the_electorate_only(client, world):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    out = world.agent("t-out", person=True)
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss, chain="c-ap")
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "k", "electorate": "inbox:t-comite",
                                         "args": {"part_id": "X1", "replacement_id": "X2", "description": "remplacer"}}).json()["id"]
    lst = lambda who: client.get("/approvals", headers=tok("user", who)).json()["approvals"]
    got = lst("t-p1")
    assert [a["id"] for a in got] == [ap] and got[0]["args"]["replacement_id"] == "X2" and got[0]["chainId"] == "c-ap" and got[0]["votes"] == 0
    assert lst(out) == []
    world.post(f"/approvals/{ap}/votes", ps[0], {"decision": "approve"}, kind="user")
    assert lst("t-p1") == [] and len(lst("t-p2")) == 1 and lst("t-p2")[0]["votes"] == 1       # already voted: no longer listed


def test_topology_state_and_agent_card(client, world, tq):
    h = login(client, "admin")
    t = client.get("/graph/topology", headers=h).json()
    ids = {a["id"] for a in t["agents"]}
    assert {"coordinateur", "qualite", "pont-kg", "chef-projet", "comite-3"} <= ids
    assert {"from": "coordinateur", "to": "ingenierie"} in t["supervises"]
    assert {"from": "ing-qualite", "to": "incidents"} in t["canSendTo"]
    assert {"id": "inbox:comite", "topic": False} in t["inboxes"] and {"id": "incidents", "topic": True} in t["inboxes"]
    assert any(r["id"] == "rt-qualite-incidents" and r["listensTo"] == "incidents" and r["deliversTo"] == "inbox:qualite" for r in t["routines"])
    assert next(a for a in t["agents"] if a["id"] == "pont-kg")["kind"] == "rule"
    # stage state: an open session makes the agent busy, with its last status sentence
    a = world.agent("t-a", tools=["set_status"])
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "I am looking at the leak"})
    st = {x["id"]: x for x in client.get("/graph/state", headers=h).json()["agents"]}
    assert st["t-a"]["busy"] is True and st["t-a"]["lastStatus"]["text"] == "I am looking at the leak"
    assert st["t-a"]["pending"] == 0 and st["qualite"]["busy"] is False
    world.trigger(a)
    assert {x["id"]: x for x in client.get("/graph/state", headers=h).json()["agents"]}["t-a"]["pending"] >= 1
    card = client.get("/graph/agent/coordinateur", headers=h).json()
    assert card["version"]["model"] == "gemini-2.5-flash" and card["mandate"]["purpose"] and card["supervisors"] == []
    assert set(card["subordinates"]) == {"ingenierie", "essais", "planification"}
    assert next(t for t in card["tools"] if t["name"] == "launch_modification") == {"name": "launch_modification", "effect": "irreversible", "approval": "2-of-3"}
    assert client.get("/graph/agent/inconnu", headers=h).status_code == 404


def test_rights_paths_match_the_scope_exactly(client, world):
    """The "rights" view must show nothing the scope computation does not grant, nor omit anything."""
    boss, r, a, sub, p = (world.agent(x) for x in ("t-boss", "t-r", "t-a", "t-sub", "t-pp"))
    mgr, emp = world.agent("t-mgr", person=True), world.agent("t-emp", person=True)
    world.supervises(boss, r); world.supervises(r, sub); world.supervises(mgr, emp)
    world.send_to(a, "inbox:t-r", "inbox:t-pp")
    sa = world.session(a)
    world.remember(a, sa, "fact of a")
    world.send(a, sa, ["inbox:t-r"], attachMemory={"mode": "snapshot"})                   # goes up to boss
    world.send(a, sa, ["inbox:t-pp"], attachMemory={"mode": "snapshot", "private": True})   # stays with p
    h = login(client, "admin")
    for who in (boss, r, a, sub, p, mgr, emp):
        kind = "user" if who in (mgr, emp) else "svc"
        scope = {s["id"] for s in client.get("/scope", headers=tok(kind, who)).json()["scopes"]}
        shown = client.get(f"/graph/rights/{who}", headers=h).json()["memories"]
        assert {m["memoryId"] for m in shown} == scope, who
        for m in shown:
            assert len(m["nodes"]) == len(m["rels"]) + 1 and m["nodes"][0] == who and m["nodes"][-1] == m["memoryId"]
    by = lambda who: {m["memoryId"]: m for m in client.get(f"/graph/rights/{who}", headers=h).json()["memories"]}
    assert by(boss)["mem:t-sub"]["nodes"] == ["t-boss", "t-r", "t-sub", "mem:t-sub"]
    assert by(boss)["mem:t-sub"]["rels"] == ["SUPERVISES", "SUPERVISES", "HAS_MEMORY"] and by(boss)["mem:t-sub"]["kind"] == "memory"
    via = by(boss)["mem:t-a"]                                                            # via the message received by t-r, higher up
    assert via["kind"] == "message" and via["nodes"][:4] == ["t-boss", "t-r", "inbox:t-r", via["nodes"][3]] and via["nodes"][4].startswith("")
    assert via["rels"] == ["SUPERVISES", "HAS_INBOX", "HAS_DAY", "RECEIVED", "CAN_READ"] and via["nodes"][-1] == "mem:t-a"
    assert "mem:t-a" in by(p) and "mem:t-a" in by(r) and "mem:t-a" in by(boss)           # private sharing does not go up:
    assert by(p)["mem:t-a"]["nodes"][1] == "inbox:t-pp"
    assert "mem:t-emp" not in by(mgr)                                                    # supervision of a person: no access


def test_kg_neighborhood_respects_kg_rights(client):
    pm, qe, ad = login(client, "chef-projet"), login(client, "ing-qualite"), login(client, "admin")
    r = client.get("/graph/kg/produit/neighborhood", params={"key": "PRT-0045"}, headers=qe)
    assert r.status_code == 200
    d = r.json()
    names = {n["id"] for n in d["nodes"]}
    assert "PRT-0045" in names and "PRT-0001" in names and any(n.startswith("TST-") for n in names)    # ancestors up to the root, tests
    assert any(x["type"] == "COVERS" for x in d["rels"]) and any(x["type"] == "CONTAINS" for x in d["rels"])
    assert client.get("/graph/kg/projet/neighborhood", params={"key": "TSK-05"}, headers=qe).status_code == 403      # no CAN_QUERY
    t = client.get("/graph/kg/projet/neighborhood", params={"key": "TSK-05"}, headers=pm).json()
    assert {n["id"] for n in t["nodes"]} >= {"TSK-05"} and all(x["type"] in ("DEPENDS_ON", "ASSIGNED_TO") for x in t["rels"])
    assert client.get("/graph/kg/projet/neighborhood", params={"key": "TSK-05"}, headers=ad).status_code == 200
    assert client.get("/graph/kg/inconnu/neighborhood", params={"key": "x"}, headers=ad).status_code == 404


def test_timeline_merges_tools_votes_routines_and_commitments(client, world):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3"), "query_kg", "commit"])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-comite")
    sid = world.session(boss)
    world.post("/tools/calls", boss, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "k1"})
    world.post("/tools/calls/k1/end", boss, {"status": "completed"})
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L", "electorate": "inbox:t-comite"}).json()["id"]
    world.post(f"/approvals/{ap}/votes", ps[0], {"decision": "approve"}, kind="user")
    world.post("/commitments", boss, {"sessionId": sid, "to": ps[0], "description": "livrer", "dueInMinutes": 10})
    items = client.get("/timeline", params={"hours": 1}, headers=login(client, "admin")).json()["items"]
    kinds = {i["kind"] for i in items}
    assert {"tool", "vote", "commitment", "routine-next"} <= kinds
    assert [i["t"] for i in items] == sorted(i["t"] for i in items)
    assert any(i["kind"] == "vote" and i["actor"] == "t-p1" and i["label"] == "approve" for i in items)
    assert any(i["kind"] == "tool" and i["label"] == "query_kg" and i["status"] == "completed" and i["end"] for i in items)
