import type { StreamEvent } from "./types";

/** Avatar states (spec) and their source: one normalized stream event -> one animation. */
export type Mode = "idle" | "woken" | "thinking" | "tool" | "sending" | "learning" | "waiting" | "error";

export interface AvatarState {
  mode: Mode;
  busy: boolean;                 // a session is open
  waiting: boolean;              // commitment or approval pending (persists after the session ends)
  until: number | null;          // end of a temporary state (ms)
  bubble?: string;               // short sentence (StatusUpdate)
  note?: string;                 // brief note (e.g. vote): keeps its own lifetime, another event does not erase it
  noteUntil?: number | null;
  tool?: string;                 // tool in progress
  target?: string | null;        // envelope recipient
  pulse: number;                 // incremented on each new visual event (re-triggers animations)
  at: number;                    // time of the last event (ms): used to detect a stopped runtime
}
export type States = Record<string, AvatarState>;
export interface Ctx { persons: ReadonlySet<string> }

export const TTL = { woken: 1600, sending: 1400, learning: 1500, error: 2800, note: 3500 } as const;
/** A "busy" agent with no new event for this long is considered idle (runtime stopped, session lost). */
export const STALE_BUSY_MS = 60_000;
/** Woken but with no sign of activity (no status or tool): shorter delay. */
export const STALE_WOKEN_MS = 20_000;

export const blank = (): AvatarState => ({ mode: "idle", busy: false, waiting: false, until: null, pulse: 0, at: 0 });

const rest = (s: AvatarState): AvatarState =>
  s.busy ? { ...s, mode: "thinking", until: null } : s.waiting ? { ...s, mode: "waiting", until: null } : { ...s, mode: "idle", until: null, bubble: undefined, tool: undefined };

/** Applies an event; pure function (tested without a browser). */
export function reduce(states: States, ev: StreamEvent, now: number, ctx: Ctx): States {
  const actor = ev.actor;
  if (!actor) return states;
  const cur = states[actor] ?? blank();
  const p = cur.pulse + 1;
  let next: AvatarState;
  switch (ev.type) {
    case "woken":
      next = { ...cur, mode: "woken", busy: !ctx.persons.has(actor), waiting: false, until: now + TTL.woken, pulse: p, bubble: undefined, tool: undefined };
      break;
    case "status":
      next = { ...cur, mode: "thinking", busy: true, waiting: false, until: null, bubble: String(ev.payload.text ?? ""), tool: undefined, pulse: p };
      break;
    case "tool.start":
      next = { ...cur, mode: "tool", busy: true, waiting: false, until: null, tool: ev.target ?? String(ev.payload.tool ?? ""), pulse: p };
      break;
    case "tool.end":
      next = rest({ ...cur, tool: undefined, pulse: p });
      break;
    case "sent":
      next = { ...cur, mode: "sending", until: now + TTL.sending, target: ev.target, pulse: p };
      break;
    case "learned":
      next = { ...cur, mode: "learning", until: now + TTL.learning, pulse: p };
      break;
    case "vote": {
      const d = String(ev.payload.decision ?? "");
      const text = d === "approve" ? "I approve" : "I reject";
      next = { ...cur, mode: "thinking", until: now + TTL.note, bubble: text, note: text, noteUntil: now + TTL.note, pulse: p };
      break;
    }
    case "waiting":
      next = { ...cur, mode: "waiting", waiting: true, until: null, pulse: p };
      break;
    case "idle":
      next = rest({ ...cur, busy: false, pulse: p });
      break;
    case "error":
      next = { ...cur, mode: "error", until: now + TTL.error, pulse: p };
      break;
    default:
      return states;
  }
  return { ...states, [actor]: { ...next, at: now } };
}

/** Expires temporary states (and brief notes, which have their own deadline). */
export function settle(states: States, now: number): States {
  let changed = false;
  const out: States = {};
  for (const [id, st] of Object.entries(states)) {
    let s = st;
    if (s.until !== null && s.until <= now) {
      s = rest(s);
      changed = true;
    } else if (s.busy && s.until === null && s.at > 0 && now - s.at > (s.bubble === undefined && s.tool === undefined ? STALE_WOKEN_MS : STALE_BUSY_MS)) {
      s = rest({ ...s, busy: false });
      changed = true;
    }
    if (s.note !== undefined && s.noteUntil != null && s.noteUntil <= now) {
      s = { ...s, note: undefined, noteUntil: undefined };
      changed = true;
    }
    out[id] = s;
  }
  return changed ? out : states;
}

export const MODE_LABEL: Record<Mode, string> = {
  idle: "Idle", woken: "Woken", thinking: "Thinking", tool: "Using a tool",
  sending: "Sending", learning: "Learning", waiting: "Waiting", error: "Error",
};

/** Clock of an event: a recent event counts as "now" (tolerates slight clock skew);
 *  an old event (history replayed on connection) keeps its real date, so its animations have already expired. */
export const HISTORICAL_MS = 5000;
export function eventClock(ev: StreamEvent, wall: number): { now: number; historical: boolean } {
  const t = Date.parse(ev.t);
  if (Number.isNaN(t) || wall - t <= HISTORICAL_MS) return { now: wall, historical: false };
  return { now: t, historical: true };
}
