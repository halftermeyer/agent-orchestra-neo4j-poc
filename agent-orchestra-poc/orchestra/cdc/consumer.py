import json
import logging
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from itertools import groupby

from neo4j.exceptions import ClientError, TransientError

from orchestra import predicate
from orchestra.cdc.gateway_client import GatewayError
from orchestra.cdc.normalize import kg_changes, normalize_tx

log = logging.getLogger("orchestra.cdc")


class Stats:
    def __init__(self):
        self.events = self.tx = self.errors = self.routed = self.woken = self.cursor_resets = 0
        self.lags = deque(maxlen=1000)       # ms between commit and processing

    def snapshot(self) -> dict:
        l = sorted(self.lags)
        pct = lambda p: round(l[min(len(l) - 1, int(len(l) * p))], 1) if l else None
        return {"events": self.events, "tx": self.tx, "errors": self.errors, "routed": self.routed,
                "woken": self.woken, "cursorResets": self.cursor_resets, "lagMs": {"p50": pct(0.5), "p95": pct(0.95), "max": round(l[-1], 1) if l else None}}


class Consumer:
    """One cursor per database; at-least-once processing, idempotent effects (deterministic message ids)."""

    def __init__(self, settings, source, gw, cursors, hub):
        self.s, self.source, self.gw, self.cursors, self.hub = settings, source, gw, cursors, hub
        self.stats = Stats()
        self._msgs = OrderedDict()
        self._owners = {}

    # ---------- curseurs ----------
    def init_cursors(self):
        """First start: begin from the current position (no seed replay)."""
        for db in self.s.dbs:
            if self.cursors.get(db) is None:
                self.cursors.set(db, self.source.current(db))

    # ---------- boucle ----------
    def poll_once(self) -> int:
        return sum(self.poll_db(db) for db in self.s.dbs)

    def poll_db(self, db: str) -> int:
        cursor = self.cursors.get(db)
        try:
            events = self.source.fetch(db, cursor)
        except (TransientError, ClientError) as e:
            if not any(c in (e.code or "") for c in ("ChangeDataCapture.FutureIdentifier", "ChangeDataCapture.InvalidIdentifier")):
                raise
            # the cursor does not match this log (database recreated: beyond its end; or another database). Nothing to catch up.
            log.warning("cursor of %s does not belong to the log (database recreated?): reset to the current position", db)
            self.cursors.set(db, self.source.current(db))
            self.stats.cursor_resets += 1
            return 0
        if not events:
            return 0
        for tx_id, grp in groupby(events, key=lambda e: e["txId"]):
            tx = list(grp)
            try:
                self._process(db, tx)
            except GatewayError as e:
                if e.transient:
                    raise                     # do not advance the cursor: retry
                self.stats.errors += 1
                log.error("tx %s skipped (%s)", tx_id, e)
            self.stats.tx += 1
            self.stats.events += len(tx)
            self._record_lag(tx[0])
        self.cursors.set(db, events[-1]["id"])
        return len(events)

    def run(self, stop):
        self.init_cursors()
        while not stop.is_set():
            try:
                n = self.poll_once()
            except Exception as e:  # database or gateway unavailable: retry
                self.stats.errors += 1
                log.error("poll failed: %s", type(e).__name__)
                n = 0
            if n == 0:
                stop.wait(self.s.poll_interval)

    def _record_lag(self, e):
        try:
            t = datetime.fromisoformat(e["metadata"]["txCommitTime"])
            self.stats.lags.append((datetime.now(timezone.utc) - t).total_seconds() * 1000)
        except Exception:
            pass

    # ---------- traitement ----------
    def _process(self, db: str, tx: list[dict]):
        if db == self.s.orchestra_db:
            stream, received = normalize_tx(tx)
            for ev in stream:
                self.hub.publish(ev)
            for r in received:
                self._on_received(**r)
            self._system_notifications(tx)
        else:
            self._on_kg_tx(db, tx)

    def _system_notifications(self, tx: list[dict]):
        """Graph decisions that must wake someone: approval decided -> the requester;
        budget exhausted -> the auditor ("sends it to the auditor")."""
        for e in tx:
            ev = e["event"]
            if ev["eventType"] != "n" or ev["operation"] != "u":
                continue
            before, after = (ev["state"].get("before") or {}).get("properties", {}), (ev["state"].get("after") or {}).get("properties", {})
            chain = ((e["metadata"].get("txMetadata") or {}).get("chainId")) or None
            if "Approval" in ev["labels"] and before.get("status") == "pending" and after.get("status") in ("approved", "rejected"):
                who = after["requestedBy"]
                word = "approved" if after["status"] == "approved" else "rejected"
                self._deliver_system(f"approval:{after['id']}:{after['status']}", f"approval:{after['id']}", who, f"inbox:{who}",
                                     f"Approval {after['id']} ({after.get('policy')}) was {word} by the committee.",
                                     {"kind": "approval-decided", "approvalId": after["id"], "status": after["status"]}, chain)
            elif ("Chain" in ev["labels"] and before.get("status") == "active" and after.get("status") == "suspended"
                  and after.get("suspendReason") in ("budget", "tokens")):
                self._deliver_system(f"chain-suspended:{after['id']}", "gateway", "auditeur", "inbox:auditeur",
                                     f"Chain {after['id']} is suspended ({after.get('suspendReason')} exhausted).",
                                     {"kind": "chain-suspended", "chainId": after["id"], "reason": after.get("suspendReason"),
                                      "spent": after.get("spent"), "budget": after.get("budget")}, None)

    def _deliver_system(self, mid, sender, acting, inbox, body, payload, chain):
        try:
            self.gw.deliver(id=mid, **{"from": sender}, actingAgent=acting, inbox=inbox, performative="inform", body=body,
                            payload=payload, chainId=chain)
        except GatewayError as e:
            if e.transient:
                raise
            self.stats.errors += 1
            log.warning("notification %s refused (%s)", mid, e.status)

    def _message(self, mid: str) -> dict:
        if mid not in self._msgs:
            self._msgs[mid] = self.gw.message(mid)
            if len(self._msgs) > 2000:
                self._msgs.popitem(last=False)
        return self._msgs[mid]

    def _owners_of(self, inbox: str) -> dict:
        hit = self._owners.get(inbox)
        if hit and time.monotonic() - hit[0] < self.s.owners_ttl:
            return hit[1]
        v = self.gw.owners(inbox)
        self._owners[inbox] = (time.monotonic(), v)
        return v

    def _on_received(self, inbox: str, messageId: str, t: str):
        msg = self._message(messageId)
        own = self._owners_of(inbox)
        base = {"messageId": messageId, "performative": msg["performative"], "chainId": msg["chainId"], "inbox": inbox}
        kind = (msg.get("payload") or {}).get("kind")
        if kind:
            base["kind"] = kind                      # used for the replay chapters
        if own["topic"]:
            self.hub.publish({"t": t, "type": "sent", "actor": msg["from"], "target": inbox, "payload": {**base, "topic": True}})
            self._route(msg, inbox)
            return
        for o in own["owners"]:
            self.hub.publish({"t": t, "type": "sent", "actor": msg["from"], "target": o["id"], "payload": base})
            # rights: no wake-up for a quarantined agent or a suspended chain
            if o["person"]:
                self.hub.publish({"t": t, "type": "woken", "actor": o["id"], "target": None, "payload": base})
            elif not o["quarantined"] and msg["chainStatus"] == "active":
                self.hub.publish({"t": t, "type": "woken", "actor": o["id"], "target": None, "payload": base})
                self.hub.wake(o["id"], base)
                self.stats.woken += 1

    def _route(self, msg: dict, topic: str):
        """Topic routing: structured filter (never Cypher), then delivery via the gateway."""
        for r in self.gw.topic_routines(topic):
            if r["owner"] == msg["from"]:
                continue                       # an agent does not consume its own publications
            try:
                if r["filter"] and not predicate.evaluate(json.loads(r["filter"]), msg.get("payload"), msg):
                    continue
            except Exception as e:
                log.error("invalid filter (routine %s): %s", r["id"], e)
                continue
            try:
                self.gw.deliver(id=f"evt:{r['id']}:{msg['id']}", **{"from": f"routine:{r['id']}"}, actingAgent=r["owner"],
                                inbox=r["deliverTo"], performative="inform", body=msg["body"] or "", payload=msg.get("payload"),
                                chainId=msg["chainId"], aboutEvent=msg["id"])
                self.stats.routed += 1
            except GatewayError as e:
                if e.transient:
                    raise
                self.stats.errors += 1
                log.warning("routine %s: delivery refused (%s)", r["id"], e.status)
                self.hub.publish({"t": datetime.now(timezone.utc).isoformat(), "type": "error", "actor": r["owner"],
                                  "target": r["deliverTo"], "payload": {"routine": r["id"], "status": e.status, "reason": e.body[:200]}})

    # ---------- KG : pont + EntityRef ----------
    def _on_kg_tx(self, db: str, tx: list[dict]):
        changes = kg_changes(tx)
        meta = tx[0]["metadata"]
        if db in self.s.bridge_dbs:
            kg_id = self.s.kg_dbs[db]
            tx_id = tx[0]["txId"]
            chain = (meta.get("txMetadata") or {}).get("chainId")
            payload = {"kind": "kg-raw", "kgDb": db, "txId": tx_id, "committedAt": meta.get("txCommitTime"),
                       "changeCount": len(changes), "changes": changes[: self.s.max_changes_in_raw],
                       "truncated": len(changes) > self.s.max_changes_in_raw}
            self.gw.deliver(id=f"raw:{db}:{tx_id}", **{"from": self.s.bridge_agent}, actingAgent=self.s.bridge_agent,
                            inbox=f"kg.{kg_id}.raw", performative="inform", body=f"{len(changes)} change(s) in {db} (tx {tx_id})",
                            payload=payload, chainId=chain)
        self._sync_refs(db, tx)

    def _sync_refs(self, db: str, tx: list[dict]):
        for e in tx:
            ev = e["event"]
            if ev["eventType"] == "n" and "Entity" in ev["labels"]:
                before = (ev["state"].get("before") or {}).get("properties", {})
                after = (ev["state"].get("after") or {}).get("properties", {})
                key = after.get("id") or before.get("id")
                if ev["operation"] == "u" and before.get("name") != after.get("name") and after.get("name"):
                    self.gw.sync_ref(db=db, key=key, op="update", label=after["name"])
                elif ev["operation"] == "d":
                    self.gw.sync_ref(db=db, key=key, op="delete")
            elif ev["eventType"] == "r" and ev["type"] == "SAME_AS" and ev["operation"] == "c":
                from orchestra.cdc.normalize import _key
                a, b = _key(ev["start"], "Entity", "id"), _key(ev["end"], "Entity", "id")
                if a and b:
                    self.gw.sync_ref(db=db, key=a, op="same_as", target=b)
