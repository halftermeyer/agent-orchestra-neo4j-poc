import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api } from "./api";
import { eventClock, reduce, settle, type States } from "./avatarState";
import { GraphView } from "./GraphView";
import { PERFORMATIVE_FR, TOOL_FR, fmtTime } from "./labels";
import { advance, chaptersOf, eventsBetween, makeReplay, rebase, SPEEDS, stateAt, type Replay } from "./replayEngine";
import { Scene } from "./Scene";
import { Ctx, useApp, type Flight } from "./store";
import type { RecordingInfo, RunInfo, StreamEvent } from "./types";

const TICK_MS = 50;
const WINDOW_FR: Record<string, string> = { sent: "envoie", woken: "est réveillé", status: "pense", "tool.start": "utilise", "tool.end": "a fini avec", learned: "apprend", vote: "vote", waiting: "attend", idle: "a terminé", error: "erreur" };

/** Acteurs sans fiche d'agent : routines, décisions du comité, passerelle. */
export function systemName(id: string): string {
  if (id.startsWith("approval:")) return "Décision du comité";
  if (id.startsWith("routine:")) return `Routine ${id.slice(8).replace(/^rt-/, "")}`;
  if (id === "gateway") return "Passerelle";
  return id.replace(/^inbox:/, "");
}

export function describeEvent(e: StreamEvent, name: (id: string) => string): string {
  const who = name(e.actor ?? "—"), to = e.target ? name(e.target) : "";
  switch (e.type) {
    case "sent": return `${who} → ${to} : ${PERFORMATIVE_FR[String(e.payload.performative)] ?? "message"}${e.payload.kind ? ` · ${e.payload.kind}` : ""}`;
    case "status": return `${who} : « ${e.payload.text} »`;
    case "tool.start": case "tool.end": return `${who} ${WINDOW_FR[e.type]} ${TOOL_FR[to] ?? to}`;
    case "learned": return `${who} apprend : ${e.payload.statement ?? ""}`;
    case "vote": return `${who} ${e.payload.decision === "approve" ? "approuve" : "refuse"}`;
    case "waiting": return `${who} attend${to ? ` (${TOOL_FR[to] ?? to})` : ""}`;
    case "error": return `${who} · erreur${e.payload.reason ? ` (${e.payload.reason})` : e.payload.error ? ` : ${e.payload.error}` : ""}`;
    default: return `${who} ${WINDOW_FR[e.type] ?? e.type}`;
  }
}

const fmtElapsed = (ms: number) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

/** Relecture : le même flux normalisé qu'en direct, reconstruit depuis le graphe ou lu dans un enregistrement. */
export function ReplayView() {
  const app = useApp();
  const { names, persons } = app;
  const name = useCallback((id: string) => names.get(id) ?? systemName(id), [names]);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [recs, setRecs] = useState<RecordingInfo[]>([]);
  const [source, setSource] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [title, setTitle] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"scene" | "graphe" | "journal">("scene");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(5);
  const [compress, setCompress] = useState(true);
  const [follow, setFollow] = useState("");
  const [vt, setVt] = useState(0);
  const [states, setStates] = useState<States>({});
  const [flights, setFlights] = useState<Flight[]>([]);
  const [sends, setSends] = useState<{ from: string; to: string; at: number }[]>([]);

  const vtRef = useRef(0);
  const statesRef = useRef<States>({});
  const idRef = useRef(0);
  const ctx = useMemo(() => ({ persons }), [persons]);

  useEffect(() => {
    Api.runs().then(setRuns).catch(() => undefined);
    Api.recordings().then(setRecs).catch(() => undefined);
  }, []);

  const seek = useCallback((to: number, r: Replay | null = replay) => {
    if (!r) return;
    const t = Math.min(Math.max(to, r.t0 - 1), r.t1);
    vtRef.current = t;
    statesRef.current = rebase(stateAt(r, t, ctx), t, Date.now());
    setVt(t); setStates(statesRef.current); setFlights([]); setSends([]);
  }, [replay, ctx]);

  const load = async () => {
    setErr(null); setPlaying(false);
    try {
      let events: StreamEvent[]; let label = "";
      if (source.startsWith("run:")) { const id = source.slice(4); events = await Api.replayEvents({ runId: id }); label = runs.find((r) => r.id === id)?.name ?? "Enregistrement"; }
      else if (source.startsWith("rec:")) { const d = await Api.recording(source.slice(4)); events = d.events; label = d.name ?? source.slice(4); }
      else { events = await Api.replayEvents({ since: new Date(Date.now() - 24 * 3600_000).toISOString() }); label = "Dernières 24 h (reconstruit depuis le graphe)"; }
      const r = makeReplay(events);
      setReplay(r); setTitle(label); setFollow("");
      seek(r.t0 - 1, r);
    } catch (e) { setErr(String(e)); }
  };

  // la lecture : le temps virtuel avance à vitesse × horloge murale ; chaque événement franchi alimente les mêmes réducteurs qu'en direct
  useEffect(() => {
    if (!playing || !replay) return;
    let last = Date.now();
    const timer = setInterval(() => {
      const wall = Date.now(), dt = wall - last; last = wall;
      const prev = vtRef.current, next = advance(replay, prev, dt, speed, compress);
      const evs = eventsBetween(replay, prev, next);
      let s = statesRef.current;
      const nf: Flight[] = [], ns: { from: string; to: string; at: number }[] = [];
      for (const ev of evs) {
        s = reduce(s, ev, wall, ctx);
        if (ev.type === "sent" && ev.actor && ev.target) { nf.push({ id: ++idRef.current, from: ev.actor, to: ev.target, at: wall }); ns.push({ from: ev.actor, to: ev.target, at: wall }); }
      }
      s = settle(s, wall);
      statesRef.current = s; vtRef.current = next;
      setStates(s); setVt(next);
      setFlights((f) => [...f.filter((x) => wall - x.at < 1500), ...nf]);
      setSends((x) => [...x.filter((y) => wall - y.at < 10000), ...ns]);
      if (next >= replay.t1 && evs.length === 0) setPlaying(false);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [playing, replay, speed, compress, ctx]);

  const chapters = useMemo(() => (replay ? chaptersOf(replay) : []), [replay]);
  const shown = useMemo(() => (replay ? replay.events.slice(0, eventsBetween(replay, replay.t0 - 2, vt).length) : []), [replay, vt]);
  const log = useMemo(() => shown.filter((e) => !follow || e.actor === follow || e.target === follow).slice(-14).reverse(), [shown, follow]);
  const actors = useMemo(() => [...new Set((replay?.events ?? []).map((e) => e.actor).filter((a): a is string => !!a && names.has(a)))], [replay, names]);

  // compteurs de la scène à l'instant rejoué (et non l'état actuel du graphe) : faits appris et messages reçus non encore traités
  const live = useMemo(() => {
    const out: Record<string, import("./types").AgentLive> = {};
    for (const a of app.topology?.agents ?? []) out[a.id] = { id: a.id, busy: false, lastStatus: null, pending: 0, commitments: 0, inputRequired: 0, facts: 0 };
    const open = new Map<string, number>();
    for (const e of shown) {
      if (e.type === "learned" && e.actor && out[e.actor]) out[e.actor].facts += 1;
      if (e.type === "sent" && e.target && out[e.target]) open.set(e.target, (open.get(e.target) ?? 0) + 1);
      if (e.type === "idle" && e.actor) open.set(e.actor, 0);               // la session a traité sa boîte
    }
    for (const [id, n] of open) if (out[id]) out[id].pending = n;
    return out;
  }, [shown, app.topology]);

  const value = useMemo(() => ({ ...app, live, states, stateOf: (id: string) => states[id] ?? { mode: "idle" as const, busy: false, waiting: false, until: null, pulse: 0, at: 0 },
    flights, recentSends: sends, connected: true, follow: follow || null, replay: true }), [app, live, states, flights, sends, follow]);

  const atEnd = !!replay && vt >= replay.t1;
  const togglePlay = () => { if (!replay) return; if (atEnd) seek(replay.t0 - 1); setPlaying((p) => !p); };

  return (
    <div className="replay" data-testid="replay">
      <div className="card replay-source">
        <label>Source <select value={source} onChange={(e) => setSource(e.target.value)} data-testid="replay-source">
          <option value="">Dernières 24 h (reconstruit depuis le graphe)</option>
          {runs.map((r) => <option key={r.id} value={`run:${r.id}`}>Enregistrement · {r.name}{r.endedAt ? "" : " (en cours)"}</option>)}
          {recs.map((r) => <option key={r.slug} value={`rec:${r.slug}`}>Fichier · {r.name ?? r.slug} ({r.events} événements)</option>)}
        </select></label>
        <button onClick={load} data-testid="replay-load">Charger</button>
        {replay && <span className="muted" data-testid="replay-title">{title} · {replay.events.length} événements · durée {fmtElapsed(replay.t1 - replay.t0)}</span>}
        {err && <span className="error">{err}</span>}
      </div>
      {replay && (
        <div className="card controls" data-testid="replay-controls">
          <div className="row">
            <button className="play" onClick={togglePlay} data-testid="replay-play">{playing ? "⏸ Pause" : atEnd ? "↺ Rejouer" : "▶ Lecture"}</button>
            <span className="speeds" role="group" aria-label="Vitesse">{SPEEDS.map((s) => <button key={s} className={`seg ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)} data-testid={`replay-speed-${s}`}>×{s}</button>)}</span>
            <label><input type="checkbox" checked={compress} onChange={(e) => setCompress(e.target.checked)} data-testid="replay-compress" /> Compresser les temps morts</label>
            <label>Suivre <select value={follow} onChange={(e) => setFollow(e.target.value)} data-testid="replay-follow">
              <option value="">— personne —</option>{actors.map((a) => <option key={a} value={a}>{name(a)}</option>)}</select></label>
            <span className="clock" data-testid="replay-time">{fmtElapsed(vt - replay.t0)} / {fmtElapsed(replay.t1 - replay.t0)}</span>
          </div>
          <input type="range" className="slider" min={replay.t0} max={replay.t1} step={100} value={Math.max(vt, replay.t0)} onChange={(e) => { setPlaying(false); seek(Number(e.target.value)); }}
            aria-label="Barre de temps" data-testid="replay-slider" />
          <div className="chapters" data-testid="replay-chapters">
            {chapters.map((c, i) => (
              <button key={c.id} className="chapter" style={{ top: (i % 2) * 24, left: `${replay.t1 === replay.t0 ? 0 : ((c.t - replay.t0) / (replay.t1 - replay.t0)) * 100}%` }}
                onClick={() => { seek(c.t - 1); setPlaying(true); }} data-testid={`chapter-${c.id}`} title={`${c.label} · ${fmtTime(new Date(c.t).toISOString())}`}>{c.label}</button>))}
            {chapters.length === 0 && <span className="muted">Aucun chapitre repéré dans cet enregistrement.</span>}
          </div>
        </div>
      )}
      {replay && (
        <Ctx.Provider value={value}>
          <div className="toolbar">
            {([["scene", "Scène"], ["graphe", "Graphe"], ["journal", "Journal"]] as const).map(([k, l]) => <button key={k} className={`seg ${view === k ? "on" : ""}`} onClick={() => setView(k)} data-testid={`replay-view-${k}`}>{l}</button>)}
          </div>
          {view === "scene" && <div className="replay-stage"><Scene /><ol className="log" data-testid="replay-log">{log.map((e, i) => <li key={`${e.t}${i}`}><time>{fmtTime(e.t)}</time> {describeEvent(e, name)}</li>)}</ol></div>}
          {view === "graphe" && <GraphView />}
          {view === "journal" && <ol className="log full" data-testid="replay-journal">{shown.slice().reverse().map((e, i) => <li key={`${e.t}${i}`}><time>{fmtTime(e.t)}</time> <span className={`pill pill-${e.type.replace(".", "-")}`}>{e.type}</span> {describeEvent(e, name)}</li>)}</ol>}
        </Ctx.Provider>
      )}
      {!replay && <p className="muted pad">Choisissez une source et cliquez sur « Charger » : la relecture rejoue l'enregistrement sur la scène et le graphe, comme en direct.</p>}
    </div>
  );
}

// eventClock est ré-exporté pour que les tests de l'interface vérifient la cohérence direct / relecture
export { eventClock };
