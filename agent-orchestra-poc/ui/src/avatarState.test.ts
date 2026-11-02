import { describe, expect, it } from "vitest";
import { blank, eventClock, HISTORICAL_MS, reduce, settle, STALE_BUSY_MS, STALE_WOKEN_MS, TTL, type Ctx, type States } from "./avatarState";
import type { EventType, StreamEvent } from "./types";

const ev = (type: EventType, actor: string | null, payload: Record<string, unknown> = {}, target: string | null = null): StreamEvent =>
  ({ t: "2026-01-01T00:00:00Z", type, actor, target, payload });
const ctx: Ctx = { persons: new Set(["chef-projet"]) };
const run = (events: [StreamEvent, number][], start: States = {}) => events.reduce((s, [e, now]) => reduce(s, e, now, ctx), start);

describe("états des avatars", () => {
  it("au repos par défaut ; un événement sans acteur ne change rien", () => {
    expect(blank().mode).toBe("idle");
    const s: States = {};
    expect(reduce(s, ev("woken", null), 0, ctx)).toBe(s);
  });

  it("réveillé -> réfléchit (phrase) -> outil -> retour à la réflexion -> repos", () => {
    let s = run([[ev("woken", "qualite"), 0]]);
    expect(s.qualite.mode).toBe("woken");
    expect(s.qualite.busy).toBe(true);
    s = reduce(s, ev("status", "qualite", { text: "Je qualifie l'incident" }), 100, ctx);
    expect(s.qualite).toMatchObject({ mode: "thinking", bubble: "Je qualifie l'incident", until: null });
    s = reduce(s, ev("tool.start", "qualite", {}, "query_kg"), 200, ctx);
    expect(s.qualite).toMatchObject({ mode: "tool", tool: "query_kg" });
    s = reduce(s, ev("tool.end", "qualite", {}, "query_kg"), 300, ctx);
    expect(s.qualite).toMatchObject({ mode: "thinking", tool: undefined, bubble: "Je qualifie l'incident" });
    s = reduce(s, ev("idle", "qualite"), 400, ctx);
    expect(s.qualite).toMatchObject({ mode: "idle", busy: false, bubble: undefined });
  });

  it("l'état « réveillé » expire : un agent passe en réflexion, une personne au repos", () => {
    let s = run([[ev("woken", "qualite"), 0], [ev("woken", "chef-projet"), 0]]);
    expect(settle(s, TTL.woken - 1)).toBe(s);                       // pas encore
    s = settle(s, TTL.woken);
    expect(s.qualite.mode).toBe("thinking");
    expect(s["chef-projet"].mode).toBe("idle");
  });

  it("envoie : cible mémorisée, puis retour à l'état de fond", () => {
    let s = run([[ev("woken", "coordinateur"), 0], [ev("status", "coordinateur", { text: "x" }), 10], [ev("sent", "coordinateur", {}, "essais"), 20]]);
    expect(s.coordinateur).toMatchObject({ mode: "sending", target: "essais" });
    s = settle(s, 20 + TTL.sending);
    expect(s.coordinateur.mode).toBe("thinking");
  });

  it("apprend : étincelle temporaire", () => {
    let s = run([[ev("learned", "essais", { factId: "f" }, "mem:essais"), 0]]);
    expect(s.essais.mode).toBe("learning");
    expect(settle(s, TTL.learning).essais.mode).toBe("idle");
  });

  it("attend : persiste après la fin de session, jusqu'au prochain réveil", () => {
    let s = run([[ev("woken", "coordinateur"), 0], [ev("waiting", "coordinateur", {}, "launch_modification"), 10]]);
    expect(s.coordinateur.mode).toBe("waiting");
    s = reduce(s, ev("tool.end", "coordinateur"), 20, ctx);
    s = reduce(s, ev("idle", "coordinateur"), 30, ctx);
    expect(s.coordinateur).toMatchObject({ mode: "waiting", busy: false, waiting: true });
    s = reduce(s, ev("woken", "coordinateur"), 40, ctx);
    expect(s.coordinateur).toMatchObject({ mode: "woken", waiting: false });
  });

  it("erreur : rouge temporaire, puis retour à l'état de fond", () => {
    let s = run([[ev("woken", "ingenierie"), 0], [ev("error", "ingenierie", { error: "KG indisponible" }), 5]]);
    expect(s.ingenierie.mode).toBe("error");
    s = settle(s, 5 + TTL.error);
    expect(s.ingenierie.mode).toBe("thinking");
  });

  it("vote : bulle brève sur la personne qui vote", () => {
    let s = run([[ev("vote", "comite-1", { decision: "approve" }, "ap1"), 0]]);
    expect(s["comite-1"]).toMatchObject({ mode: "thinking", bubble: "J'approuve" });
    s = settle(s, TTL.note);
    expect(s["comite-1"]).toMatchObject({ mode: "idle", bubble: undefined });
  });

  it("un agent occupé sans nouvelles retombe au repos (runtime arrêté), pas avant", () => {
    const s = run([[ev("status", "qualite", { text: "a" }), 1000]]);
    expect(settle(s, 1000 + STALE_BUSY_MS)).toBe(s);
    const later = settle(s, 1000 + STALE_BUSY_MS + 1);
    expect(later.qualite).toMatchObject({ mode: "idle", busy: false, bubble: undefined });
    const w = run([[ev("status", "coordinateur", { text: "a" }), 0], [ev("waiting", "coordinateur"), 10]]);
    expect(settle(w, 10 + 10 * STALE_BUSY_MS).coordinateur.mode).toBe("waiting");     // une attente légitime ne s'efface pas
  });

  it("réveillé sans aucune activité : retombe au repos plus vite qu'un agent qui a déjà parlé", () => {
    const T = 1000;
    let s = run([[ev("woken", "qualite"), T]]);
    s = settle(s, T + TTL.woken);                                 // « réveillé » expiré -> en attente de travail
    expect(s.qualite.mode).toBe("thinking");
    expect(settle(s, T + STALE_WOKEN_MS).qualite.mode).toBe("thinking");
    expect(settle(s, T + STALE_WOKEN_MS + 1).qualite.mode).toBe("idle");
    const talked = run([[ev("woken", "essais"), T], [ev("status", "essais", { text: "x" }), T + 1]]);
    expect(settle(talked, T + STALE_WOKEN_MS + 5).essais.mode).toBe("thinking");
  });

  it("settle ne recrée pas l'objet s'il n'y a rien à expirer", () => {
    const s = run([[ev("status", "qualite", { text: "a" }), 0]]);
    expect(settle(s, 10_000)).toBe(s);
  });
});

describe("horloge des événements", () => {
  const at = (ms: number): StreamEvent => ({ ...ev("woken", "qualite"), t: new Date(ms).toISOString() });
  it("un événement récent compte comme maintenant", () => {
    expect(eventClock(at(100_000 - 1200), 100_000)).toEqual({ now: 100_000, historical: false });
    expect(eventClock(at(100_000 + 3000), 100_000).historical).toBe(false);          // léger décalage d'horloge
  });
  it("un événement ancien garde sa date : son animation est déjà expirée", () => {
    const old = at(100_000 - HISTORICAL_MS - 1);
    const c = eventClock(old, 100_000);
    expect(c.historical).toBe(true);
    let s = reduce({}, old, c.now, ctx);
    expect(s.qualite.mode).toBe("woken");
    s = settle(s, 100_000);
    expect(s.qualite.mode).not.toBe("woken");                                        // expiré dès le premier tick
  });
  it("date illisible : traité comme récent", () => {
    expect(eventClock({ ...ev("woken", "x"), t: "pas une date" }, 5).historical).toBe(false);
  });
});
