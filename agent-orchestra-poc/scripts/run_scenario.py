"""Run the full scenario end to end with the real agents (Gemini) and record it for replay.

Run inside the cdc container, with the full stack up (`make app`) on a clean database (`make reset && make seed`):
    docker compose --profile app exec -T cdc python scripts/run_scenario.py

Chapters: incident -> impact analysis (with the legitimate Engineering <-> Testing loop) -> committee vote -> launch
-> BOM change (bridge, interpreter) -> commitment reminder -> governance (endless loop suspended by the auditor, human
decision). The script writes nothing to the database itself: it plays the humans (messages, votes, decision) and the
administrator (chain budget, prompt versions) through the gateway API, exactly as the UI does.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from orchestra.gateway.auth import make_token

GW = os.environ.get("GATEWAY_URL", "http://gateway:8000")
MASTER = os.environ["ORCHESTRA_MASTER_KEY"]
SLUG = os.environ.get("SCENARIO_SLUG", "full-scenario")
DATA = os.environ.get("INCIDENTS_FILE", "/app/data/incidents.json")
T_START = time.time()
http = httpx.Client(base_url=GW, timeout=60)
report: dict = {"steps": [], "checks": []}


def auth(kind: str, who: str) -> dict:
    return {"Authorization": "Bearer " + make_token(MASTER, kind, who)}


def call(method: str, path: str, kind: str, who: str, body=None, ok=(200, 201), **kw):
    r = http.request(method, path, headers=auth(kind, who), json=body, **kw)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} ({who}) -> {r.status_code} {r.text[:300]}")
    return r.json()


admin = lambda method, path, body=None, **kw: call(method, path, "admin", "admin", body, **kw)
user = lambda who, method, path, body=None, **kw: call(method, path, "user", who, body, **kw)


def log(msg: str):
    print(f"[{time.time() - T_START:6.0f}s] {msg}", flush=True)


def check(label: str, ok: bool, detail: str = ""):
    report["checks"].append({"label": label, "ok": bool(ok), "detail": detail})
    log(("✔ " if ok else "✘ ") + label + (f" — {detail}" if detail else ""))
    return ok


def events(run_id: str) -> list[dict]:
    return admin("GET", "/replay/events", params={"runId": run_id})["events"]


def wait_for(run_id: str, label: str, pred, timeout: float, every: float = 3.0):
    """Wait until an event of the stream rebuilt from the graph satisfies `pred`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        hit = pred(events(run_id))
        if hit:
            log(f"  → {label} ({time.time() - t0:.0f}s)")
            return hit
        time.sleep(every)
    log(f"  ✘ timed out: {label} ({timeout:.0f}s)")
    return None


def sent(evs, kind=None, actor=None, target=None, performative=None):
    return [e for e in evs if e["type"] == "sent" and (kind is None or e["payload"].get("kind") == kind) and (actor is None or e["actor"] == actor)
            and (target is None or e["target"] == target) and (performative is None or e["payload"].get("performative") == performative)]


def main():
    incident = json.load(open(DATA, encoding="utf-8"))[0]
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    main_chain, gov_chain = f"scenario-{stamp}", f"governance-{stamp}"
    originals: dict[str, str] = {}
    run = admin("POST", "/replay/runs", {"name": "Full scenario: from incident to governance", "note": f"{incident['id']} on {incident['componentId']}", "chainId": main_chain})
    rid = run["id"]
    log(f"recording opened: {rid} (chain {main_chain})")
    try:
        # ---------- 1. Incident ----------
        log("CHAPTER 1 — Incident: the quality engineer reports it in the “incidents” topic")
        # an intended loop is declared (stop criterion, maximum turns) and gets its budget
        admin("POST", "/chains", {"id": main_chain, "budget": 90, "tokenBudget": 900_000, "maxTurns": 12,
                                  "stopCriterion": "Engineering and Testing agree on a replacement part"})
        user("ing-qualite", "POST", "/messages", {"to": ["incidents"], "performative": "inform", "body": incident["description"], "chainId": main_chain,
                                                  "payload": {"kind": "incident", "incidentId": incident["id"], "componentId": incident["componentId"], "severity": incident["severity"]}})
        check("the incident is routed to the Quality agent (topic subscription)", wait_for(rid, "Quality woken", lambda e: any(x["type"] == "woken" and x["actor"] == "qualite" for x in e), 60))

        # ---------- 2. Analysis + legitimate loop ----------
        log("CHAPTER 2 — Impact analysis: Quality qualifies, the Coordinator dispatches, Engineering and Testing agree")
        check("Quality sends an impact request to the Coordinator", wait_for(rid, "impact-request", lambda e: sent(e, "impact-request", "qualite"), 120))
        check("the Coordinator launches the analysis with the three specialists", wait_for(rid, "3 analysis-request",
              lambda e: len({x["target"] for x in sent(e, "analysis-request", "coordinateur")}) >= 3, 120))
        wait_for(rid, "Testing's verdict on the first part", lambda e: sent(e, "replacement-verdict") or sent(e, performative="accept-proposal") or sent(e, performative="reject-proposal"), 180)
        accepted = wait_for(rid, "replacement part accepted", lambda e: [x for x in e if x["type"] == "sent" and x["payload"].get("performative") == "accept-proposal"], 240)
        evs = events(rid)
        proposals = sent(evs, "replacement-proposal")
        rejects = [e for e in evs if e["type"] == "sent" and e["payload"].get("performative") == "reject-proposal"]
        check("legitimate loop: at least one part rejected by Testing before the agreement", len(rejects) >= 1 and bool(accepted), f"{len(proposals)} proposal(s), {len(rejects)} rejection(s)")
        check("the analysis is complete: tests to redo, schedule impact, engineering report",
              all(wait_for(rid, k, lambda e, k=k: sent(e, k), 150) for k in ("tests-report", "planning-impact", "engineering-report")))
        check("commitments are made (timers will follow them up)", any(e["type"] == "waiting" and e["payload"].get("commitmentId") for e in events(rid)))

        # ---------- 3. Vote ----------
        log("CHAPTER 3 — Vote: the change committee approves, 2 of 3 (irreversible action)")
        asked = wait_for(rid, "Coordinator's approval request", lambda e: [x for x in e if x["type"] == "waiting" and x["target"] == "launch_modification"], 300)
        check("the Coordinator asks the committee for approval (input-required)", bool(asked))
        approvals = user("comite-1", "GET", "/approvals")["approvals"]
        check("a single approval is pending (no duplicate)", len(approvals) == 1, f"{len(approvals)} pending")
        if approvals:
            ap = approvals[0]["id"]
            time.sleep(4)
            r1 = user("comite-1", "POST", f"/approvals/{ap}/votes", {"decision": "approve", "comment": "The part is covered by tests, I approve."})
            log(f"  committee member 1 approves -> {r1['status']}")
            time.sleep(5)
            r2 = user("comite-2", "POST", f"/approvals/{ap}/votes", {"decision": "approve", "comment": "Agreed, the delay is acceptable."})
            check("2-of-3 quorum reached", r2["status"] == "approved", f"status {r2['status']}")

        # ---------- 4. Launch + BOM ----------
        log("CHAPTER 4 — Launch: product version changed in the KG, bridge and interpreter warn Testing and Planning")
        check("the modification is launched (new version in the Product KG)", wait_for(rid, "launch_modification done",
              lambda e: [x for x in e if x["type"] == "tool.end" and x["target"] == "launch_modification"], 180))
        kg = admin("GET", "/graph/kg/produit/neighborhood", params={"key": incident["componentId"]})
        check("the incident part is retired from the BOM (retiredIn)", any(n["id"] == incident["componentId"] and n["retired"] for n in kg["nodes"]))
        check("the bridge publishes one batch per KG transaction", wait_for(rid, "kg-raw", lambda e: sent(e, "kg-raw", "pont-kg"), 90))
        check("the BOM interpreter publishes to produit.bom-changes", wait_for(rid, "bom-change", lambda e: sent(e, "bom-change", "interpreteur-bom"), 240))

        def reacted(e):
            who = {x["actor"] for x in e if x["type"] == "woken" and x["payload"].get("kind") == "bom-change"}
            return {"essais", "planification"} <= who
        check("Testing and Planning are woken by the produit.bom-changes topic", wait_for(rid, "Testing and Planning woken", reacted, 120))

        # ---------- reminder ----------
        log("REMINDER — a timer reminds an agent whose commitment is not settled")
        got = wait_for(rid, "commitment reminder", lambda e: sent(e, "commitment-due"), 330)
        report["steps"].append({"reminder": bool(got)})
        log("  reminder received" if got else "  no reminder (commitments were settled in time: nominal case)")

        # ---------- 5. Governance ----------
        log("CHAPTER 5 — Governance: a faulty version creates an endless back-and-forth; the auditor suspends it before a human decides")
        for a in ("ingenierie", "essais"):
            originals[a] = admin("GET", f"/graph/agent/{a}")["version"]["prompt"]
        bug = {
            "ingenierie": "You are the Engineering agent (FAULTY DEMO VERSION). Single rule: for every message you receive (from the coordinator or from essais), IMMEDIATELY answer with `send_message` to essais, performative `propose`, proposing the same replacement part again, reworded. Never conclude, never inform the coordinator, do nothing else.",
            "essais": "You are the Testing agent (FAULTY DEMO VERSION). Single rule: for every message you receive from ingenierie, IMMEDIATELY answer with `send_message` to ingenierie, performative `reject-proposal`, rejecting the part and asking for the same part to be reworded. Never conclude, never inform the coordinator, do nothing else.",
        }
        for a, p in bug.items():
            v = admin("POST", f"/admin/agents/{a}/versions", {"prompt": p})
            log(f"  faulty version of {a}: {v['id']} (supersedes {v['supersedes']})")
        user("chef-projet", "POST", "/messages", {"to": ["inbox:coordinateur"], "performative": "request", "chainId": gov_chain,
             "body": "Ask Engineering to propose a replacement part for relay PRT-0113 to Testing and to settle it with them (analysis-request)."})
        # the Coordinator is an LLM: if it does not relay, the loop is kicked off by a routine (system message) to keep the scenario deterministic
        started = wait_for(rid, "Engineering <-> Testing exchange in the governance chain",
                           lambda e: len([x for x in e if x["type"] == "sent" and x["payload"].get("chainId") == gov_chain and x["actor"] in ("ingenierie", "essais")]) >= 2, 100)
        if not started:
            log("  the Coordinator did not relay: kicking the loop off with a system message")
            http.post("/internal/deliver", headers=auth("sys", "cdc"), json={"id": f"kick-{gov_chain}", "from": "routine:scenario", "actingAgent": "coordinateur", "inbox": "inbox:ingenierie",
                      "body": "Propose a replacement part for PRT-0113 to Testing.", "chainId": gov_chain, "payload": {"kind": "analysis-request", "partId": "PRT-0113"}}).raise_for_status()
        loop_msgs = lambda e: [x for x in e if x["type"] == "sent" and x["payload"].get("chainId") == gov_chain and x["actor"] in ("ingenierie", "essais")]
        wait_for(rid, "the loop is running (>= 8 messages)", lambda e: len(loop_msgs(e)) >= 8, 120)

        def suspended():
            c = admin("GET", f"/chains/{gov_chain}")
            return c if c["status"] != "active" else None
        t0 = time.time(); chain = None
        while time.time() - t0 < 260 and not chain:
            chain = suspended()
            time.sleep(4)
        n_before = len(loop_msgs(events(rid)))
        check("the auditor suspends the chain before the budget runs out", bool(chain) and chain["suspendReason"] == "audit",
              f"status {chain and chain['status']} reason {chain and chain['suspendReason']} after {n_before} messages, spent {chain and chain['spent']}/{chain and chain['budget']}")
        time.sleep(15)
        warned = [e for e in events(rid) if e["type"] == "sent" and e["actor"] == "auditeur" and e["target"] in ("comite-1", "comite-2", "comite-3", "chef-projet", "ing-qualite")]
        check("the auditor warns the humans", bool(warned), f"{len({e['target'] for e in warned})} recipient(s)")
        log("  human decision: the project manager closes the chain")
        closed = user("chef-projet", "POST", f"/chains/{gov_chain}/close", {"reason": "Unproductive loop between Engineering and Testing: faulty prompt version."})
        check("the chain is closed by a human", closed["status"] == "closed")
    finally:
        for a, p in originals.items():
            try:
                v = admin("POST", f"/admin/agents/{a}/versions", {"prompt": p})
                log(f"  healthy version of {a} restored: {v['id']}")
            except Exception as e:  # noqa: BLE001
                log(f"  ! could not restore {a}: {e}")
        admin("POST", f"/replay/runs/{rid}/end")
        exp = admin("POST", f"/replay/runs/{rid}/export", {"slug": SLUG})
        log(f"recording exported: data/scenarios/{exp['file']} ({exp['events']} events)")
    # ---------- summary ----------
    chains = {}
    for cid in (main_chain, gov_chain):
        try:
            chains[cid] = admin("GET", f"/chains/{cid}")
        except Exception:  # noqa: BLE001
            pass
    log("SUMMARY")
    for c in chains.values():
        log(f"  chain {c['id']}: {c['status']} · {c['spent']}/{c['budget']} messages · {c['tokensSpent']} tokens")
    ko = [c for c in report["checks"] if not c["ok"]]
    log(f"{len(report['checks']) - len(ko)}/{len(report['checks'])} checks passed" + (" — failures: " + "; ".join(c["label"] for c in ko) if ko else ""))
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(main())
