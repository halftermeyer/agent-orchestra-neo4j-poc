import json
import time
from collections import Counter

from tests.conftest import tok

ADMIN = tok("admin")


def shape(events, drop=()):
    return Counter((e["type"], e["actor"], e["target"]) for e in events if e["type"] not in drop)


def test_replay_reconstructs_the_live_stream_from_the_graph(client, world, cdc):
    """Même format, mêmes événements : la reconstruction depuis les dates du graphe égale le flux produit en direct."""
    boss = world.agent("t-boss", tools=["set_status", "query_kg", "remember", "send_message", "commit", ("launch_modification", "2-of-3")], kgs=["produit"])
    peer = world.agent("t-peer")
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-peer", "inbox:t-comite")
    t0 = time.time()
    sid = world.session(boss, chain="c-replay")
    world.post("/status", boss, {"sessionId": sid, "text": "Je prépare la synthèse"})
    world.post("/tools/calls", boss, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "q1"})
    world.post("/tools/calls/q1/end", boss, {"status": "completed"})
    world.post("/tools/calls", boss, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "q2"})
    world.post("/tools/calls/q2/end", boss, {"status": "failed", "error": "KG indisponible"})
    world.remember(boss, sid, "Le relais est défaillant")
    world.send(boss, sid, ["inbox:t-peer"], body="pour toi", payload={"kind": "analysis-request"})
    world.post("/commitments", boss, {"sessionId": sid, "to": "t-peer", "description": "livrer", "dueInMinutes": 10})
    ap = world.post("/approvals", boss, {"sessionId": sid, "tool": "launch_modification", "idempotencyKey": "L", "electorate": "inbox:t-comite"}).json()["id"]
    for p in ps[:2]:
        world.post(f"/approvals/{ap}/votes", p, {"decision": "approve"}, kind="user")
    world.c.post(f"/sessions/{sid}/close", json={"status": "input-required"}, headers=tok("svc", boss))
    cdc.drain(settle=0.8)

    r = client.get("/replay/events", headers=ADMIN)
    assert r.status_code == 200
    mine = lambda e: (e["actor"] or "").startswith("t-") or (e["target"] or "").startswith(("t-", "inbox:t-", "mem:t-"))
    rebuilt = [e for e in r.json()["events"] if mine(e)]
    live = [e for e in cdc.events if mine(e)]
    # format normalisé identique
    assert all(set(e) == {"t", "type", "actor", "target", "payload"} for e in rebuilt)
    assert shape(rebuilt, drop=("sent", "woken")) == shape(live, drop=("sent", "woken"))
    assert shape(rebuilt) == shape(live), (shape(rebuilt) - shape(live), shape(live) - shape(rebuilt))
    # ordre chronologique, kinds portés par les messages
    assert [e["t"] for e in rebuilt] == sorted(e["t"] for e in rebuilt)
    sent = next(e for e in rebuilt if e["type"] == "sent" and e["actor"] == "t-boss" and e["target"] == "t-peer")
    assert sent["payload"]["kind"] == "analysis-request" and sent["payload"]["chainId"] == "c-replay"
    assert "pj" not in sent["payload"]
    live_sent = next(e for e in live if e["type"] == "sent" and e["actor"] == "t-boss" and e["target"] == "t-peer")
    assert live_sent["payload"]["kind"] == "analysis-request"                          # le flux en direct porte aussi le kind
    # le ToolCall en attente puis repris (quorum atteint) apparaît comme en direct
    types = [(e["type"], e["payload"].get("resumed")) for e in rebuilt if e["actor"] == "t-boss" and e["target"] == "launch_modification"]
    assert types == [("waiting", None), ("tool.start", True)]
    assert time.time() - t0 < 60


def test_replay_window_by_run_and_by_time(client, world):
    a = world.agent("t-a", tools=["set_status"])
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "avant"})
    time.sleep(0.3)
    run = client.post("/replay/runs", json={"name": "essai", "note": "n"}, headers=ADMIN).json()
    time.sleep(0.3)
    world.post("/status", a, {"sessionId": sid, "text": "pendant"})
    time.sleep(0.3)
    assert client.post(f"/replay/runs/{run['id']}/end", headers=ADMIN).status_code == 200
    time.sleep(0.3)
    world.post("/status", a, {"sessionId": sid, "text": "après"})
    got = client.get("/replay/events", params={"runId": run["id"]}, headers=ADMIN).json()
    texts = [e["payload"]["text"] for e in got["events"] if e["type"] == "status"]
    assert texts == ["pendant"] and got["run"]["name"] == "essai" and got["run"]["endedAt"]
    assert [r["id"] for r in client.get("/replay/runs", headers=ADMIN).json()["runs"]] == [run["id"]]
    only_after = client.get("/replay/events", params={"since": got["to"]}, headers=ADMIN).json()["events"]
    assert [e["payload"]["text"] for e in only_after if e["type"] == "status"] == ["après"]
    assert client.get("/replay/events", params={"runId": "inconnu"}, headers=ADMIN).status_code == 404


def test_runs_are_admin_only_to_create(client, world):
    p = world.agent("t-p", person=True)
    assert client.post("/replay/runs", json={"name": "x"}, headers=tok("user", p)).status_code == 403
    assert client.post("/replay/runs", json={"name": "x"}).status_code == 401
    assert client.get("/replay/runs", headers=tok("user", p)).status_code == 200            # la lecture est ouverte aux personnes


def test_export_recording_to_a_portable_file(client, world):
    a = world.agent("t-a", tools=["set_status"])
    run = client.post("/replay/runs", json={"name": "Scénario de test", "note": "pour l'export"}, headers=ADMIN).json()
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "dans l'enregistrement"})
    client.post(f"/replay/runs/{run['id']}/end", headers=ADMIN)
    assert client.post(f"/replay/runs/{run['id']}/export", json={"slug": "../evil"}, headers=ADMIN).status_code == 404   # pas d'évasion de répertoire
    ok = client.post(f"/replay/runs/{run['id']}/export", json={"slug": "essai-export"}, headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["file"] == "essai-export.json" and ok.json()["events"] >= 3
    lst = client.get("/replay/recordings", headers=ADMIN).json()["recordings"]
    assert {"slug": "essai-export", "name": "Scénario de test", "note": "pour l'export"} == {k: lst[0][k] for k in ("slug", "name", "note")}
    doc = client.get("/replay/recordings/essai-export", headers=ADMIN).json()
    assert any(e["type"] == "status" and e["payload"]["text"] == "dans l'enregistrement" for e in doc["events"])
    assert client.get("/replay/recordings/..%2Fetc", headers=ADMIN).status_code in (404, 422)
    assert client.get("/replay/recordings/inexistant", headers=ADMIN).status_code == 404
    assert client.post(f"/replay/runs/{run['id']}/export", json={"slug": "x"}, headers=tok("user", world.agent("t-u", person=True))).status_code == 403


def test_a_human_closes_a_chain_for_good(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    p = world.agent("t-p", person=True)
    world.send_to(a, "inbox:t-b")
    sid = world.session(a, chain="c-close")
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201
    assert world.post("/chains/c-close/close", a, {"reason": "x"}).status_code == 403            # un agent ne clôt pas
    r = client.post("/chains/c-close/close", json={"reason": "boucle improductive"}, headers=tok("user", p))
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 409                                    # plus aucun envoi
    assert client.post("/chains/c-close/close", json={}, headers=tok("user", p)).status_code == 409
    assert client.post("/chains/c-close/resume", json={}, headers=ADMIN).status_code == 409        # on ne reprend pas une chaîne close


def test_one_pending_approval_per_tool_and_chain(client, world, tq):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-comite")
    req = lambda s, key: world.post("/approvals", boss, {"sessionId": s, "tool": "launch_modification", "idempotencyKey": key, "electorate": "inbox:t-comite",
                                                           "args": {"part_id": "X1", "replacement_id": "X2"}})
    s1 = world.session(boss, chain="c-one")
    first = req(s1, "k1").json()
    s2 = world.session(boss, chain="c-one")                 # réveillé une 2e fois dans la même chaîne
    again = req(s2, "k2")
    assert again.status_code == 201 and again.json()["id"] == first["id"] and again.json()["duplicateOf"] == first["id"]
    assert tq("MATCH (ap:Approval) RETURN count(ap) AS n")[0]["n"] == 1
    other = req(world.session(boss, chain="c-two"), "k3").json()                                  # autre chaîne : autre décision
    assert other["id"] != first["id"]
    for p in ps[:2]:
        world.post(f"/approvals/{first['id']}/votes", p, {"decision": "approve"}, kind="user")
    new = req(world.session(boss, chain="c-one"), "k4").json()                                    # la 1re est tranchée : une nouvelle demande est possible
    assert new["id"] not in (first["id"], other["id"]) and not new.get("replayed")
