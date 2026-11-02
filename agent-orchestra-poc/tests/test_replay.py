import json
import time
from collections import Counter

from tests.conftest import tok

ADMIN = tok("admin")


def shape(events, drop=()):
    return Counter((e["type"], e["actor"], e["target"]) for e in events if e["type"] not in drop)


def test_replay_reconstructs_the_live_stream_from_the_graph(client, world, cdc):
    """Same format, same events: the reconstruction from the graph's dates equals the live-produced stream."""
    boss = world.agent("t-boss", tools=["set_status", "query_kg", "remember", "send_message", "commit", ("launch_modification", "2-of-3")], kgs=["produit"])
    peer = world.agent("t-peer")
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-peer", "inbox:t-comite")
    t0 = time.time()
    sid = world.session(boss, chain="c-replay")
    world.post("/status", boss, {"sessionId": sid, "text": "I am preparing the summary"})
    world.post("/tools/calls", boss, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "q1"})
    world.post("/tools/calls/q1/end", boss, {"status": "completed"})
    world.post("/tools/calls", boss, {"sessionId": sid, "tool": "query_kg", "idempotencyKey": "q2"})
    world.post("/tools/calls/q2/end", boss, {"status": "failed", "error": "KG unavailable"})
    world.remember(boss, sid, "The relay is faulty")
    world.send(boss, sid, ["inbox:t-peer"], body="for you", payload={"kind": "analysis-request"})
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
    # identical normalized format
    assert all(set(e) == {"t", "type", "actor", "target", "payload"} for e in rebuilt)
    assert shape(rebuilt, drop=("sent", "woken")) == shape(live, drop=("sent", "woken"))
    assert shape(rebuilt) == shape(live), (shape(rebuilt) - shape(live), shape(live) - shape(rebuilt))
    # chronological order, kinds carried by the messages
    assert [e["t"] for e in rebuilt] == sorted(e["t"] for e in rebuilt)
    sent = next(e for e in rebuilt if e["type"] == "sent" and e["actor"] == "t-boss" and e["target"] == "t-peer")
    assert sent["payload"]["kind"] == "analysis-request" and sent["payload"]["chainId"] == "c-replay"
    assert "pj" not in sent["payload"]
    live_sent = next(e for e in live if e["type"] == "sent" and e["actor"] == "t-boss" and e["target"] == "t-peer")
    assert live_sent["payload"]["kind"] == "analysis-request"                          # the live stream also carries the kind
    # the ToolCall pending then resumed (quorum reached) appears as in live
    types = [(e["type"], e["payload"].get("resumed")) for e in rebuilt if e["actor"] == "t-boss" and e["target"] == "launch_modification"]
    assert types == [("waiting", None), ("tool.start", True)]
    assert time.time() - t0 < 60


def test_replay_window_by_run_and_by_time(client, world):
    a = world.agent("t-a", tools=["set_status"])
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "before"})
    time.sleep(0.3)
    run = client.post("/replay/runs", json={"name": "test", "note": "n"}, headers=ADMIN).json()
    time.sleep(0.3)
    world.post("/status", a, {"sessionId": sid, "text": "during"})
    time.sleep(0.3)
    assert client.post(f"/replay/runs/{run['id']}/end", headers=ADMIN).status_code == 200
    time.sleep(0.3)
    world.post("/status", a, {"sessionId": sid, "text": "after"})
    got = client.get("/replay/events", params={"runId": run["id"]}, headers=ADMIN).json()
    texts = [e["payload"]["text"] for e in got["events"] if e["type"] == "status"]
    assert texts == ["during"] and got["run"]["name"] == "test" and got["run"]["endedAt"]
    assert [r["id"] for r in client.get("/replay/runs", headers=ADMIN).json()["runs"]] == [run["id"]]
    only_after = client.get("/replay/events", params={"since": got["to"]}, headers=ADMIN).json()["events"]
    assert [e["payload"]["text"] for e in only_after if e["type"] == "status"] == ["after"]
    assert client.get("/replay/events", params={"runId": "inconnu"}, headers=ADMIN).status_code == 404


def test_runs_are_admin_only_to_create(client, world):
    p = world.agent("t-p", person=True)
    assert client.post("/replay/runs", json={"name": "x"}, headers=tok("user", p)).status_code == 403
    assert client.post("/replay/runs", json={"name": "x"}).status_code == 401
    assert client.get("/replay/runs", headers=tok("user", p)).status_code == 200            # reading is open to people


def test_export_recording_to_a_portable_file(client, world):
    a = world.agent("t-a", tools=["set_status"])
    run = client.post("/replay/runs", json={"name": "Test scenario", "note": "for the export"}, headers=ADMIN).json()
    sid = world.session(a)
    world.post("/status", a, {"sessionId": sid, "text": "in the recording"})
    client.post(f"/replay/runs/{run['id']}/end", headers=ADMIN)
    assert client.post(f"/replay/runs/{run['id']}/export", json={"slug": "../evil"}, headers=ADMIN).status_code == 404   # no directory escape
    ok = client.post(f"/replay/runs/{run['id']}/export", json={"slug": "export-test"}, headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["file"] == "export-test.json" and ok.json()["events"] >= 3
    lst = client.get("/replay/recordings", headers=ADMIN).json()["recordings"]
    assert {"slug": "export-test", "name": "Test scenario", "note": "for the export"} == {k: lst[0][k] for k in ("slug", "name", "note")}
    doc = client.get("/replay/recordings/export-test", headers=ADMIN).json()
    assert any(e["type"] == "status" and e["payload"]["text"] == "in the recording" for e in doc["events"])
    assert client.get("/replay/recordings/..%2Fetc", headers=ADMIN).status_code in (404, 422)
    assert client.get("/replay/recordings/inexistant", headers=ADMIN).status_code == 404
    assert client.post(f"/replay/runs/{run['id']}/export", json={"slug": "x"}, headers=tok("user", world.agent("t-u", person=True))).status_code == 403


def test_a_human_closes_a_chain_for_good(client, world):
    a, b = world.agent("t-a"), world.agent("t-b")
    p = world.agent("t-p", person=True)
    world.send_to(a, "inbox:t-b")
    sid = world.session(a, chain="c-close")
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 201
    assert world.post("/chains/c-close/close", a, {"reason": "x"}).status_code == 403            # an agent does not close
    r = client.post("/chains/c-close/close", json={"reason": "unproductive loop"}, headers=tok("user", p))
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert world.send(a, sid, ["inbox:t-b"]).status_code == 409                                    # no more sending
    assert client.post("/chains/c-close/close", json={}, headers=tok("user", p)).status_code == 409
    assert client.post("/chains/c-close/resume", json={}, headers=ADMIN).status_code == 409        # a closed chain cannot be resumed


def test_one_pending_approval_per_tool_and_chain(client, world, tq):
    boss = world.agent("t-boss", tools=[("launch_modification", "2-of-3")])
    ps = [world.agent(f"t-p{i}", person=True, inbox="inbox:t-comite") for i in (1, 2, 3)]
    world.send_to(boss, "inbox:t-comite")
    req = lambda s, key: world.post("/approvals", boss, {"sessionId": s, "tool": "launch_modification", "idempotencyKey": key, "electorate": "inbox:t-comite",
                                                           "args": {"part_id": "X1", "replacement_id": "X2"}})
    s1 = world.session(boss, chain="c-one")
    first = req(s1, "k1").json()
    s2 = world.session(boss, chain="c-one")                 # woken a 2nd time in the same chain
    again = req(s2, "k2")
    assert again.status_code == 201 and again.json()["id"] == first["id"] and again.json()["duplicateOf"] == first["id"]
    assert tq("MATCH (ap:Approval) RETURN count(ap) AS n")[0]["n"] == 1
    other = req(world.session(boss, chain="c-two"), "k3").json()                                  # other chain: other decision
    assert other["id"] != first["id"]
    for p in ps[:2]:
        world.post(f"/approvals/{first['id']}/votes", p, {"decision": "approve"}, kind="user")
    new = req(world.session(boss, chain="c-one"), "k4").json()                                    # the 1st is decided: a new request is possible
    assert new["id"] not in (first["id"], other["id"]) and not new.get("replayed")
