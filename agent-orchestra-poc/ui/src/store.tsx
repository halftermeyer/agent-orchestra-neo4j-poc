import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Api } from "./api";
import { blank, eventClock, reduce, settle, type AvatarState, type States } from "./avatarState";
import { EventStream } from "./events";
import type { AgentLive, Session, StreamEvent, Topology } from "./types";

export interface Flight { id: number; from: string; to: string; at: number }

export interface AppCtx {
  session: Session;
  stream: EventStream;
  connected: boolean;
  topology: Topology | null;
  names: Map<string, string>;
  persons: Set<string>;
  states: States;
  live: Record<string, AgentLive>;
  flights: Flight[];
  recentSends: { from: string; to: string; at: number }[];
  refreshTopology: () => void;
  stateOf: (id: string) => AvatarState;
  follow?: string | null;           // replay: followed agent
  replay?: boolean;
}
export const Ctx = createContext<AppCtx | null>(null);
export const useApp = () => { const c = useContext(Ctx); if (!c) throw new Error("hors contexte"); return c; };

let flightId = 0;

export function AppProvider({ session, children }: { session: Session; children: ReactNode }) {
  const stream = useMemo(() => new EventStream(), [session.token]);
  const [connected, setConnected] = useState(false);
  const [topology, setTopology] = useState<Topology | null>(null);
  const [states, setStates] = useState<States>({});
  const [live, setLive] = useState<Record<string, AgentLive>>({});
  const [flights, setFlights] = useState<Flight[]>([]);
  const sends = useRef<{ from: string; to: string; at: number }[]>([]);
  const personsRef = useRef<Set<string>>(new Set());

  const refreshTopology = useCallback(() => { Api.topology().then(setTopology).catch(() => undefined); }, []);
  useEffect(refreshTopology, [refreshTopology]);

  const persons = useMemo(() => new Set((topology?.agents ?? []).filter((a) => a.person).map((a) => a.id)), [topology]);
  personsRef.current = persons;
  const names = useMemo(() => new Map((topology?.agents ?? []).map((a) => [a.id, a.name])), [topology]);

  // initial scene state: open sessions, last status sentence, waits
  useEffect(() => {
    let alive = true;
    const load = () => Api.state().then((rows) => {
      if (!alive) return;
      setLive(Object.fromEntries(rows.map((r) => [r.id, r])));
      setStates((prev) => {
        const next = { ...prev };
        for (const r of rows) {
          if (next[r.id] && next[r.id].pulse > 0) continue;       // the stream has already mentioned this agent
          const base = blank();
          next[r.id] = r.busy ? { ...base, mode: "thinking", busy: true, bubble: r.lastStatus?.text }
            : (r.commitments > 0 || r.inputRequired > 0) ? { ...base, mode: "waiting", waiting: true } : base;
        }
        return next;
      });
    }).catch(() => undefined);
    load();
    const t = setInterval(load, 6000);                          // refreshes the counters (inboxes, memory)
    return () => { alive = false; clearInterval(t); };
  }, [session.token]);

  useEffect(() => {
    stream.start();
    const offStatus = stream.onStatus(setConnected);
    const off = stream.subscribe((ev: StreamEvent) => {
      const wall = Date.now();
      const { now, historical } = eventClock(ev, wall);
      setStates((s) => reduce(s, ev, now, { persons: personsRef.current }));
      if (ev.type === "sent" && ev.actor && ev.target && !historical) {
        sends.current = [...sends.current.filter((x) => now - x.at < 10000), { from: ev.actor, to: ev.target, at: now }];
        const f = { id: ++flightId, from: ev.actor, to: ev.target, at: now };
        setFlights((fl) => [...fl.filter((x) => now - x.at < 3000), f]);
      }
    });
    for (const ev of stream.buffer) void ev;                    // history is replayed by the server on connection
    const tick = setInterval(() => {
      const now = Date.now();
      setStates((s) => settle(s, now));
      setFlights((fl) => (fl.some((x) => now - x.at >= 1500) ? fl.filter((x) => now - x.at < 1500) : fl));
    }, 200);
    return () => { off(); offStatus(); clearInterval(tick); stream.stop(); };
  }, [stream]);

  const stateOf = useCallback((id: string) => states[id] ?? blank(), [states]);
  const value: AppCtx = { session, stream, connected, topology, names, persons, states, live, flights, recentSends: sends.current, refreshTopology, stateOf };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Re-triggers `fn` on each stream event of one of the requested types (debounced). */
export function useOnEvents(types: StreamEvent["type"][], fn: (ev: StreamEvent) => void, delay = 300) {
  const { stream } = useApp();
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = stream.subscribe((ev) => {
      if (!types.includes(ev.type)) return;
      clearTimeout(timer);
      timer = setTimeout(() => ref.current(ev), delay);
    });
    return () => { off(); clearTimeout(timer); };
  }, [stream, delay, types.join(",")]);
}
