import { describe, expect, it } from "vitest";
import { TTL, type Ctx } from "./avatarState";
import { IDLE_GAP_MS, IDLE_KEEP_MS, advance, chaptersOf, eventsBetween, makeReplay, rebase, stateAt } from "./replayEngine";
import type { EventType, StreamEvent } from "./types";

const T0 = Date.parse("2026-06-01T10:00:00Z");
const at = (sec: number, type: EventType, actor: string | null, target: string | null = null, payload: Record<string, unknown> = {}): StreamEvent =>
  ({ t: new Date(T0 + sec * 1000).toISOString(), type, actor, target, payload });
const ctx: Ctx = { persons: new Set(["ing-qualite"]) };

const scenario = makeReplay([
  at(0, "sent", "ing-qualite", "incidents", { kind: "incident" }),
  at(0.2, "woken", "qualite"),
  at(2, "status", "qualite", null, { text: "I am qualifying" }),
  at(3, "sent", "coordinateur", "ingenierie", { kind: "analysis-request" }),
  at(60, "waiting", "coordinateur", "launch_modification"),
  at(65, "vote", "comite-1", "ap", { decision: "approve" }),
  at(70, "tool.start", "coordinateur", "launch_modification", { resumed: true }),
  at(300, "error", "auditeur", "chain-x", { chainId: "chain-x", reason: "audit" }),
]);

describe("replay engine", () => {
  it("sorts events by date (stable) and bounds the recording", () => {
    const r = makeReplay([at(5, "idle", "a"), at(1, "woken", "a"), at(1, "status", "a")]);
    expect(r.events.map((e) => e.type)).toEqual(["woken", "status", "idle"]);
    expect([r.t0, r.t1]).toEqual([T0 + 1000, T0 + 5000]);
    expect(makeReplay([]).t1).toBe(0);
  });

  it("advances at speed × wall time, never past the end", () => {
    const r = scenario;
    expect(advance(r, T0, 100, 1, false)).toBe(T0 + 100);
    expect(advance(r, T0, 100, 20, false)).toBe(T0 + 2000);
    expect(advance(r, r.t1 - 10, 100, 20, false)).toBe(r.t1);
  });

  it("compresses idle gaps, but not short ones", () => {
    const r = scenario;
    const inGap = T0 + 5000;                                         // entre l'événement à 3 s et celui à 60 s
    expect(advance(r, inGap, 50, 1, false)).toBe(inGap + 50);        // sans compression : temps réel
    const jumped = advance(r, inGap, 50, 1, true);
    expect(jumped).toBe(T0 + 60_000 - IDLE_KEEP_MS + 50);            // on saute juste avant l'événement suivant
    const shortGap = T0 + 1000;                                      // 1 s avant l'événement suivant : pas de saut
    expect(advance(r, shortGap, 50, 1, true)).toBe(shortGap + 50);
    expect(IDLE_GAP_MS).toBeGreaterThan(IDLE_KEEP_MS);
  });

  it("events in (a, b]: open on the left, closed on the right", () => {
    const r = scenario;
    expect(eventsBetween(r, T0, T0 + 2000).map((e) => e.type)).toEqual(["woken", "status"]);   // exclut t=0, inclut t=2 s
    expect(eventsBetween(r, T0 - 1, T0).map((e) => e.type)).toEqual(["sent"]);
    expect(eventsBetween(r, T0 + 3000, T0 + 59_000)).toEqual([]);
  });

  it("seek: the state at a given time matches playing from the start", () => {
    const s = stateAt(scenario, T0 + 2500, ctx);
    expect(s.qualite).toMatchObject({ mode: "thinking", bubble: "I am qualifying", busy: true });
  });

  it("seek: temporary animations that already expired do not come back", () => {
    const s = stateAt(scenario, T0 + 2500, ctx);
    expect(s["ing-qualite"].mode).toBe("idle");                       // 0 + 1400 ms < 2,5 s
    const early = stateAt(scenario, T0 + 300, ctx);
    expect(early.qualite.mode).toBe("woken");
    expect(early["ing-qualite"].mode).toBe("sending");
    expect(early.qualite.until).toBe(T0 + 200 + TTL.woken);
  });

  it("waiting persists until the agent resumes; before the start, nobody has a state", () => {
    expect(stateAt(scenario, T0 + 65_000, ctx).coordinateur.mode).toBe("waiting");        // demande de validation à 60 s
    expect(stateAt(scenario, T0 + 71_000, ctx).coordinateur.mode).toBe("tool");           // quorum atteint : reprise à 70 s
    expect(stateAt(scenario, T0 - 1, ctx)).toEqual({});
  });

  it("rebase: moves deadlines from the virtual clock to the wall clock", () => {
    const s = stateAt(scenario, T0 + 300, ctx);
    const wall = 5_000_000;
    const r = rebase(s, T0 + 300, wall);
    expect(r.qualite.until).toBe(wall + (T0 + 200 + TTL.woken - (T0 + 300)));
    expect(r["ing-qualite"].until).toBe(wall + (T0 + TTL.sending - (T0 + 300)));
    expect(rebase({ x: { ...s.qualite, until: null, at: 0 } }, 1, 2).x).toMatchObject({ until: null, at: 0 });
  });

  it("chapters: incident, analysis, vote, launch, governance, in scenario order", () => {
    const ch = chaptersOf(scenario);
    expect(ch.map((c) => c.id)).toEqual(["incident", "analyse", "vote", "lancement", "gouvernance"]);
    expect(ch.map((c) => (c.t - T0) / 1000)).toEqual([0, 3, 60, 70, 300]);
    expect(ch[0].label).toBe("Incident");
  });

  it("chapters: only those present in the recording are offered", () => {
    expect(chaptersOf(makeReplay([at(0, "status", "a", null, { text: "x" })]))).toEqual([]);
    expect(chaptersOf(makeReplay([at(0, "sent", "x", "incidents", { kind: "incident" })])).map((c) => c.id)).toEqual(["incident"]);
  });
});
