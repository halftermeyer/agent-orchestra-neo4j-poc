"""Scheduler for `cron` and `once` routines. `nextRunAt` is computed here (in the application)."""
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from orchestra.cdc.gateway_client import GatewayError

log = logging.getLogger("orchestra.cdc.scheduler")
UTC = timezone.utc


def iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def next_after(cron: str, tz: str, after: datetime) -> datetime:
    local = after.astimezone(ZoneInfo(tz or "UTC"))
    return croniter(cron, local).get_next(datetime).astimezone(UTC)


class Scheduler:
    def __init__(self, settings, gw, hub=None):
        self.s, self.gw, self.hub = settings, gw, hub
        self.fired = self.skipped = 0

    def tick(self, now: datetime | None = None) -> int:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        n = 0
        for r in self.gw.due(iso(now)):
            try:
                n += self._handle(r, now)
            except GatewayError as e:
                if e.transient:
                    raise
                log.error("routine %s : %s", r["id"], e)
        return n

    def _late_ok(self, r: dict, slot: datetime, now: datetime) -> bool:
        """misfire = skip (default): a slot that is too old is ignored; misfire = fire: trigger anyway."""
        return r["misfire"] == "fire" or (now - slot).total_seconds() <= self.s.misfire_grace

    def _deliver(self, r: dict, slot: datetime) -> str | None:
        payload = json.loads(r["payload"]) if r.get("payload") else {}
        try:
            # CAN_SEND_TO (or own inbox) is re-checked by the gateway on every trigger
            self.gw.deliver(id=f"{r['id']}@{iso(slot)}", **{"from": f"routine:{r['id']}"}, actingAgent=r["owner"],
                            inbox=r["deliverTo"], performative="inform",
                            body=payload.get("body") or f"Routine {r['id']} ({iso(slot)})", payload=payload or None)
            self.fired += 1
            return None
        except GatewayError as e:
            if e.transient:
                raise
            return f"{e.status} {e.body[:200]}"

    def _handle(self, r: dict, now: datetime) -> int:
        if r["trigger"] == "cron":
            nxt = next_after(r["cron"], r["tz"], now)
            if r["nextRunAt"] is None:                        # first sighting: schedule, do not trigger
                self.gw.advance(r["id"], nextRunAt=iso(nxt))
                return 0
            slot = parse(r["nextRunAt"])
            if not self._late_ok(r, slot, now):
                self.skipped += 1
                self.gw.advance(r["id"], nextRunAt=iso(nxt), skipped=iso(slot))
                return 0
            err = self._deliver(r, slot)
            self.gw.advance(r["id"], nextRunAt=iso(nxt), fired=None if err else iso(now), error=err)
            return 0 if err else 1
        slot = parse(r["runAt"])                              # once
        if not self._late_ok(r, slot, now):
            self.skipped += 1
            self.gw.advance(r["id"], skipped=iso(slot), disable=True)
            return 0
        err = self._deliver(r, slot)
        self.gw.advance(r["id"], fired=iso(now), error=err, disable=True)
        return 0 if err else 1
