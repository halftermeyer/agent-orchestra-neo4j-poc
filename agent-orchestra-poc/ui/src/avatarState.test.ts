import { describe, expect, it } from "vitest";
import { blank, eventClock, HISTORICAL_MS, reduce, settle, STALE_BUSY_MS, STALE_WOKEN_MS, TTL, type Ctx, type States } from "./avatarState";
import type { EventType, StreamEvent } from "./types";

const ev = (type: EventType, actor: string | null, payload: Record<string, unknown> = {}, target: string | null = null): StreamEvent =>
  ({ t: "2026-01-01T00:00:00Z", type, actor, target, payload });
const ctx: Ctx = { persons: new Set(["chef-projet"]) };
const run = (events: [StreamEvent, number][], start: States = {}) => events.reduce((s, [e, now]) => reduce(s, e, now, ctx), start);

describe("avatar states", () => {
  it("idle by default; an event without an actor changes nothing", () => {
    expect(blank().mode).toBe("idle");
    const s: States = {};
    expect(reduce(s, ev("woken", null), 0, ctx)).toBe(s);
  });

  it("woken -> thinking (sentence) -> tool -> back to thinking -> idle", () => {
    let s = run([[ev("woken", "qualite"), 0]]);
    expect(s.qualite.mode).toBe("woken");
    expect(s.qualite.busy).toBe(true);
    s = reduce(s, ev("status", "qualite", { text: "I am qualifying the incident" }), 100, ctx);
    expect(s.qualite).toMatchObject({ mode: "thinking", bubble: "I am qualifying the incident", until: null });
    s = reduce(s, ev("tool.start", "qualite", {}, "query_kg"), 200, ctx);
    expect(s.qualite).toMatchObject({ mode: "tool", tool: "query_kg" });
    s = reduce(s, ev("tool.end", "qualite", {}, "query_kg"), 300, ctx);
    expect(s.qualite).toMatchObject({ mode: "thinking", tool: undefined, bubble: "I am qualifying the incident" });
    s = reduce(s, ev("idle", "qualite"), 400, ctx);
    expect(s.qualite).toMatchObject({ mode: "idle", busy: false, bubble: undefined });
  });

  it("the “woken” state expires: an agent goes to thinking, a person to idle", () => {
    let s = run([[ev("woken", "qualite"), 0], [ev("woken", "chef-projet"), 0]]);
    expect(settle(s, TTL.woken - 1)).toBe(s);                       // not yet
    s = settle(s, TTL.woken);
    expect(s.qualite.mode).toBe("thinking");
    expect(s["chef-projet"].mode).toBe("idle");
  });

  it("sending: target remembered, then back to the background state", () => {
    let s = run([[ev("woken", "coordinateur"), 0], [ev("status", "coordinateur", { text: "x" }), 10], [ev("sent", "coordinateur", {}, "essais"), 20]]);
    expect(s.coordinateur).toMatchObject({ mode: "sending", target: "essais" });
    s = settle(s, 20 + TTL.sending);
    expect(s.coordinateur.mode).toBe("thinking");
  });

  it("learning: temporary spark", () => {
    let s = run([[ev("learned", "essais", { factId: "f" }, "mem:essais"), 0]]);
    expect(s.essais.mode).toBe("learning");
    expect(settle(s, TTL.learning).essais.mode).toBe("idle");
  });

  it("waiting: persists after the session ends, until the next wake-up", () => {
    let s = run([[ev("woken", "coordinateur"), 0], [ev("waiting", "coordinateur", {}, "launch_modification"), 10]]);
    expect(s.coordinateur.mode).toBe("waiting");
    s = reduce(s, ev("tool.end", "coordinateur"), 20, ctx);
    s = reduce(s, ev("idle", "coordinateur"), 30, ctx);
    expect(s.coordinateur).toMatchObject({ mode: "waiting", busy: false, waiting: true });
    s = reduce(s, ev("woken", "coordinateur"), 40, ctx);
    expect(s.coordinateur).toMatchObject({ mode: "woken", waiting: false });
  });

  it("error: temporary red, then back to the background state", () => {
    let s = run([[ev("woken", "ingenierie"), 0], [ev("error", "ingenierie", { error: "KG indisponible" }), 5]]);
    expect(s.ingenierie.mode).toBe("error");
    s = settle(s, 5 + TTL.error);
    expect(s.ingenierie.mode).toBe("thinking");
  });

  it("vote: brief bubble on the person voting", () => {
    let s = run([[ev("vote", "comite-1", { decision: "approve" }, "ap1"), 0]]);
    expect(s["comite-1"]).toMatchObject({ mode: "thinking", bubble: "I approve" });
    s = settle(s, TTL.note);
    expect(s["comite-1"]).toMatchObject({ mode: "idle", bubble: undefined });
  });

  it("a busy agent with no news falls back to idle (runtime stopped), not before", () => {
    const s = run([[ev("status", "qualite", { text: "a" }), 1000]]);
    expect(settle(s, 1000 + STALE_BUSY_MS)).toBe(s);
    const later = settle(s, 1000 + STALE_BUSY_MS + 1);
    expect(later.qualite).toMatchObject({ mode: "idle", busy: false, bubble: undefined });
    const w = run([[ev("status", "coordinateur", { text: "a" }), 0], [ev("waiting", "coordinateur"), 10]]);
    expect(settle(w, 10 + 10 * STALE_BUSY_MS).coordinateur.mode).toBe("waiting");     // a legitimate wait is not cleared
  });

  it("woken with no activity: falls back to idle faster than an agent that already spoke", () => {
    const T = 1000;
    let s = run([[ev("woken", "qualite"), T]]);
    s = settle(s, T + TTL.woken);                                 // "woken" expired -> waiting for work
    expect(s.qualite.mode).toBe("thinking");
    expect(settle(s, T + STALE_WOKEN_MS).qualite.mode).toBe("thinking");
    expect(settle(s, T + STALE_WOKEN_MS + 1).qualite.mode).toBe("idle");
    const talked = run([[ev("woken", "essais"), T], [ev("status", "essais", { text: "x" }), T + 1]]);
    expect(settle(talked, T + STALE_WOKEN_MS + 5).essais.mode).toBe("thinking");
  });

  it("the vote note survives a later wake-up and expires at its own deadline", () => {
    let s = run([[ev("vote", "comite-1", { decision: "approve" }, "ap"), 1000], [ev("woken", "comite-1"), 1500]]);
    expect(s["comite-1"].mode).toBe("woken");
    expect(s["comite-1"].note).toBe("I approve");                         // the wake-up does not erase the note
    s = settle(s, 1000 + TTL.note - 1);
    expect(s["comite-1"].note).toBe("I approve");
    s = settle(s, 1000 + TTL.note);
    expect(s["comite-1"].note).toBeUndefined();
  });

  it("settle does not recreate the object when nothing expires", () => {
    const s = run([[ev("status", "qualite", { text: "a" }), 0]]);
    expect(settle(s, 10_000)).toBe(s);
  });
});

describe("event clock", () => {
  const at = (ms: number): StreamEvent => ({ ...ev("woken", "qualite"), t: new Date(ms).toISOString() });
  it("a recent event counts as now", () => {
    expect(eventClock(at(100_000 - 1200), 100_000)).toEqual({ now: 100_000, historical: false });
    expect(eventClock(at(100_000 + 3000), 100_000).historical).toBe(false);          // slight clock skew
  });
  it("an old event keeps its date: its animation has already expired", () => {
    const old = at(100_000 - HISTORICAL_MS - 1);
    const c = eventClock(old, 100_000);
    expect(c.historical).toBe(true);
    let s = reduce({}, old, c.now, ctx);
    expect(s.qualite.mode).toBe("woken");
    s = settle(s, 100_000);
    expect(s.qualite.mode).not.toBe("woken");                                        // expired from the first tick
  });
  it("unreadable date: treated as recent", () => {
    expect(eventClock({ ...ev("woken", "x"), t: "not a date" }, 5).historical).toBe(false);
  });
});
