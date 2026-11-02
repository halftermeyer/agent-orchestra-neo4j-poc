import { reduce, settle, type Ctx, type States } from "./avatarState";
import type { StreamEvent } from "./types";

/** Moteur de relecture : pur, sans horloge ni DOM. `vt` est le temps virtuel (ms epoch) de l'enregistrement. */
export interface Replay { events: StreamEvent[]; times: number[]; t0: number; t1: number }

export const IDLE_GAP_MS = 4000;      // au-delà, un temps mort est compressé
export const IDLE_KEEP_MS = 800;      // ce qu'on garde avant l'événement suivant
export const SPEEDS = [1, 2, 5, 10, 20] as const;

export function makeReplay(events: StreamEvent[]): Replay {
  const sorted = events.map((e, i) => ({ e, i, t: Date.parse(e.t) })).filter((x) => !Number.isNaN(x.t)).sort((a, b) => a.t - b.t || a.i - b.i);
  const times = sorted.map((x) => x.t);
  return { events: sorted.map((x) => x.e), times, t0: times[0] ?? 0, t1: times[times.length - 1] ?? 0 };
}

const firstAfter = (times: number[], t: number): number => {          // plus petit indice d'événement strictement après t
  let lo = 0, hi = times.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] > t) hi = mid; else lo = mid + 1; }
  return lo;
};

/** Fait avancer le temps virtuel de `dtWallMs` (horloge murale) × `speed` ; saute les temps morts si `compress`. */
export function advance(r: Replay, vt: number, dtWallMs: number, speed: number, compress: boolean): number {
  let cur = vt;
  if (compress) {
    const i = firstAfter(r.times, cur);
    if (i < r.times.length && r.times[i] - cur > IDLE_GAP_MS) cur = r.times[i] - IDLE_KEEP_MS;   // temps mort : on saute
  }
  return Math.min(cur + dtWallMs * speed, r.t1);
}

/** Événements dans l'intervalle (a, b]. */
export function eventsBetween(r: Replay, a: number, b: number): StreamEvent[] {
  return r.events.slice(firstAfter(r.times, a), firstAfter(r.times, b));
}

/** Positionnement : rejoue tout jusqu'à `vt` avec les vraies dates des événements, puis fait expirer ce qui doit l'être. */
export function stateAt(r: Replay, vt: number, ctx: Ctx): States {
  let s: States = {};
  const end = firstAfter(r.times, vt);
  for (let i = 0; i < end; i++) s = reduce(s, r.events[i], r.times[i], ctx);
  return settle(s, vt);
}

/** Passe un état calculé en temps virtuel dans l'horloge murale (les animations en cours finissent à leur heure). */
export function rebase(states: States, vt: number, wall: number): States {
  const shift = wall - vt;
  const out: States = {};
  for (const [id, s] of Object.entries(states)) out[id] = { ...s, until: s.until === null ? null : s.until + shift, at: s.at === 0 ? 0 : s.at + shift,
    noteUntil: s.noteUntil == null ? s.noteUntil : s.noteUntil + shift };
  return out;
}

export interface Chapter { id: string; label: string; t: number }

/** Chapitres du scénario, repérés dans le flux : incident, analyse, vote, lancement, gouvernance. */
export function chaptersOf(r: Replay): Chapter[] {
  const rules: { id: string; label: string; test: (e: StreamEvent) => boolean }[] = [
    { id: "incident", label: "Incident", test: (e) => e.type === "sent" && e.payload.kind === "incident" },
    { id: "analyse", label: "Impact analysis", test: (e) => e.type === "sent" && e.payload.kind === "analysis-request" },
    { id: "vote", label: "Committee vote", test: (e) => (e.type === "waiting" && e.target === "launch_modification") || e.type === "vote" },
    { id: "lancement", label: "Launch", test: (e) => (e.type === "tool.start" && e.target === "launch_modification" && e.payload.resumed === true) || (e.type === "tool.end" && e.target === "launch_modification") },
    { id: "gouvernance", label: "Governance", test: (e) => (e.type === "error" && typeof e.payload.chainId === "string") || (e.type === "sent" && e.payload.kind === "chain-suspended") },
  ];
  const out: Chapter[] = [];
  for (const rule of rules) {
    const i = r.events.findIndex(rule.test);
    if (i >= 0) out.push({ id: rule.id, label: rule.label, t: r.times[i] });
  }
  return out.sort((a, b) => a.t - b.t);
}
