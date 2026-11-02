import type { StreamEvent } from "./types";

/** États des avatars (spec) et leur source : un événement du flux normalisé -> une animation. */
export type Mode = "idle" | "woken" | "thinking" | "tool" | "sending" | "learning" | "waiting" | "error";

export interface AvatarState {
  mode: Mode;
  busy: boolean;                 // une session est ouverte
  waiting: boolean;              // engagement ou validation en attente (persiste après la fin de session)
  until: number | null;          // fin d'un état temporaire (ms)
  bubble?: string;               // phrase courte (StatusUpdate)
  tool?: string;                 // outil en cours
  target?: string | null;        // destinataire de l'enveloppe
  pulse: number;                 // incrémenté à chaque nouvel événement visuel (re-déclenche les animations)
  at: number;                    // date du dernier événement (ms) : sert à détecter un runtime arrêté
}
export type States = Record<string, AvatarState>;
export interface Ctx { persons: ReadonlySet<string> }

export const TTL = { woken: 1600, sending: 1400, learning: 1500, error: 2800, note: 3500 } as const;
/** Un agent « occupé » sans nouvel événement depuis ce délai est considéré au repos (runtime arrêté, session perdue). */
export const STALE_BUSY_MS = 60_000;
/** Réveillé mais sans aucun signe d'activité (ni statut ni outil) : délai plus court. */
export const STALE_WOKEN_MS = 20_000;

export const blank = (): AvatarState => ({ mode: "idle", busy: false, waiting: false, until: null, pulse: 0, at: 0 });

const rest = (s: AvatarState): AvatarState =>
  s.busy ? { ...s, mode: "thinking", until: null } : s.waiting ? { ...s, mode: "waiting", until: null } : { ...s, mode: "idle", until: null, bubble: undefined, tool: undefined };

/** Applique un événement ; fonction pure (testée sans navigateur). */
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
      next = { ...cur, mode: "thinking", until: now + TTL.note, bubble: d === "approve" ? "J'approuve" : "Je refuse", pulse: p };
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

/** Fait expirer les états temporaires. */
export function settle(states: States, now: number): States {
  let changed = false;
  const out: States = {};
  for (const [id, s] of Object.entries(states)) {
    if (s.until !== null && s.until <= now) {
      out[id] = rest(s);
      changed = true;
    } else if (s.busy && s.until === null && s.at > 0 && now - s.at > (s.bubble === undefined && s.tool === undefined ? STALE_WOKEN_MS : STALE_BUSY_MS)) {
      out[id] = rest({ ...s, busy: false });
      changed = true;
    } else out[id] = s;
  }
  return changed ? out : states;
}

export const MODE_LABEL: Record<Mode, string> = {
  idle: "Au repos", woken: "Réveillé", thinking: "Réfléchit", tool: "Utilise un outil",
  sending: "Envoie", learning: "Apprend", waiting: "Attend", error: "Erreur",
};

/** Horloge d'un événement : un événement récent compte comme « maintenant » (tolère un léger décalage d'horloge) ;
 *  un événement ancien (historique rejoué à la connexion) garde sa vraie date, donc ses animations sont déjà expirées. */
export const HISTORICAL_MS = 5000;
export function eventClock(ev: StreamEvent, wall: number): { now: number; historical: boolean } {
  const t = Date.parse(ev.t);
  if (Number.isNaN(t) || wall - t <= HISTORICAL_MS) return { now: wall, historical: false };
  return { now: t, historical: true };
}
