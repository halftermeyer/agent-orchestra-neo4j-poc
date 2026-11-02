import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import type { Node, Relationship } from "@neo4j-nvl/base";
import { useEffect, useMemo, useRef, useState } from "react";
import { Api } from "./api";
import { COLORS, flowHeat, kgGraph, rightsGraph, topologyGraph } from "./graphTransform";
import { SHARE_LABEL, STATUS_LABEL, TOOL_LABEL, fmtDateTime } from "./labels";
import { useApp } from "./store";
import type { AgentCard, KgNeighborhood, RightsPath } from "./types";

type Mode = "topologie" | "flux" | "droits" | "kg";
const MODES: [Mode, string][] = [["topologie", "Topology"], ["flux", "Flow"], ["droits", "Rights"], ["kg", "Knowledge graphs"]];

function Canvas({ nodes, rels, onNode }: { nodes: Node[]; rels: Relationship[]; onNode?: (id: string) => void }) {
  const ref = useRef<{ fit?: (ids: string[]) => void } | null>(null);
  const ids = nodes.map((n) => n.id);
  const fit = () => ref.current?.fit?.(ids);
  // re-fits the view when the layout settles, and when the set of nodes changes
  const key = ids.join("|");
  useEffect(() => { const t = setTimeout(fit, 900); return () => clearTimeout(t); }, [key]);
  return (
    <div className="nvl" data-testid="nvl" data-nodes={nodes.length} data-rels={rels.length}>
      <button className="ghost recenter" onClick={fit} data-testid="recenter">Recenter</button>
      <InteractiveNvlWrapper
        ref={ref as never}
        nodes={nodes} rels={rels}
        nvlOptions={{ renderer: "canvas", layout: "forceDirected", initialZoom: 0.9, minZoom: 0.2, maxZoom: 4, disableTelemetry: true } as never}
        nvlCallbacks={{ onLayoutDone: fit } as never}
        mouseEventCallbacks={{ onNodeClick: (n: Node) => onNode?.(n.id), onZoomAndPan: true, onPan: true, onDrag: true }}
      />
    </div>
  );
}

export function GraphView() {
  const { topology, names, recentSends, session } = useApp();
  const [mode, setMode] = useState<Mode>("topologie");
  const [opts, setOpts] = useState({ showSend: false, showAudits: false, showKgAccess: true, showRoutines: true });
  const [card, setCard] = useState<AgentCard | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (mode !== "flux") return; const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, [mode]);

  const topo = useMemo(() => topology ? topologyGraph(topology, mode === "flux" ? { ...opts, showSend: true } : opts) : null, [topology, opts, mode]);
  const flux = useMemo(() => {
    if (!topo || mode !== "flux") return topo;
    const heat = flowHeat(recentSends, now);
    const owner = new Map((topology?.agents ?? []).filter((a) => a.inbox).map((a) => [a.inbox as string, a.id]));
    const hot = new Map<string, number>();
    for (const [k, v] of heat) { const [f, t] = k.split(">"); hot.set(`send:${f}>${owner.get(t) ?? t}`, v); hot.set(`send:${f}>${t}`, v); }
    return { nodes: topo.nodes, rels: topo.rels.map((r) => { const h = hot.get(r.id); return h ? { ...r, color: COLORS.hot, width: 2 + 6 * h } : r; }) };
  }, [topo, mode, now, recentSends, topology]);
  const cardSeq = useRef(0);
  const openCard = (id: string) => {
    if (!names.has(id)) return;
    const mine = ++cardSeq.current;
    Api.card(id).then((c) => { if (mine === cardSeq.current) setCard(c); }).catch(() => { if (mine === cardSeq.current) setCard(null); });
  };

  return (
    <div className="graph" data-testid="graph">
      <div className="toolbar">
        {MODES.map(([m, label]) => <button key={m} className={`seg ${mode === m ? "on" : ""}`} onClick={() => setMode(m)} data-testid={`mode-${m}`}>{label}</button>)}
        {(mode === "topologie") && (
          <span className="toggles">
            {([["showRoutines", "Subscriptions"], ["showSend", "Allowed sends"], ["showAudits", "Audit"], ["showKgAccess", "KG access"]] as const).map(([k, l]) => (
              <label key={k}><input type="checkbox" checked={opts[k]} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} /> {l}</label>))}
          </span>
        )}
        {mode === "flux" && <span className="muted">Edges light up on every message sent (8 s).</span>}
      </div>
      <div className="graph-body">
        <div className="canvas-col">
          {(mode === "topologie" || mode === "flux") && flux && <Canvas nodes={flux.nodes} rels={flux.rels} onNode={openCard} />}
          {mode === "droits" && <Rights initial={session.kind === "user" ? session.id : "coordinateur"} />}
          {mode === "kg" && <KgExplorer />}
        </div>
        {card && (mode === "topologie" || mode === "flux") && <CardPanel card={card} onClose={() => setCard(null)} />}
      </div>
    </div>
  );
}

function CardPanel({ card, onClose }: { card: AgentCard; onClose: () => void }) {
  const { names } = useApp();
  const n = (id: string) => names.get(id) ?? id;
  return (
    <aside className="card side" data-testid="agent-card">
      <button className="ghost close" onClick={onClose} aria-label="Close">×</button>
      <h3>{card.name}</h3>
      <p className="muted">{card.person ? card.title ?? "Human" : `${card.version?.kind === "rule" ? "Rule-based" : "LLM"} agent${card.version?.model ? ` · ${card.version.model}` : ""}`}{card.quarantined ? " · quarantined" : ""}</p>
      {card.mandate && <><h4>Mandate</h4><p>{card.mandate.purpose}</p><p className="muted">Scope: {card.mandate.scope}</p><p className="muted">Success: {card.mandate.successCriteria}</p></>}
      {card.supervisors.length > 0 && <p><b>Supervised by</b> {card.supervisors.map(n).join(", ")}</p>}
      {card.subordinates.length > 0 && <p><b>Supervises</b> {card.subordinates.map(n).join(", ")}</p>}
      {card.audits.length > 0 && <p><b>Audits</b> {card.audits.map(n).join(", ")}</p>}
      {card.tools.length > 0 && <><h4>Tools</h4><ul className="chips">{card.tools.map((t) => <li key={t.name} className={t.effect === "irreversible" ? "danger" : ""} title={t.effect}>{TOOL_LABEL[t.name] ?? t.name}{t.approval !== "none" ? ` (${t.approval})` : ""}</li>)}</ul></>}
      {card.routines.length > 0 && <><h4>Routines</h4><ul className="plain">{card.routines.map((r) => <li key={r.id}><code>{r.id}</code> · {r.trigger}{r.cron ? ` ${r.cron}` : ""}</li>)}</ul></>}
      {card.commitments.length > 0 && <><h4>Open commitments</h4><ul className="plain">{card.commitments.map((c) => <li key={c.id}>{c.description} → {n(c.to)} before {fmtDateTime(c.dueAt)}</li>)}</ul></>}
      <p><b>Memory</b>: {card.facts} fact{card.facts > 1 ? "s" : ""}</p>
      {card.statuses.length > 0 && <><h4>Latest statuses</h4><ul className="plain">{card.statuses.map((s, i) => <li key={i}>{s.text}</li>)}</ul></>}
      {card.toolCalls.length > 0 && <><h4>Latest tool calls</h4><ul className="plain">{card.toolCalls.map((t, i) => <li key={i}>{TOOL_LABEL[t.tool] ?? t.tool} · {STATUS_LABEL[t.status] ?? t.status}</li>)}</ul></>}
      {card.version && !card.person && <details><summary>Prompt ({card.version.id})</summary><pre>{card.version.prompt}</pre></details>}
    </aside>
  );
}

function Rights({ initial }: { initial: string }) {
  const { topology, names } = useApp();
  const [agent, setAgent] = useState(initial);
  const [paths, setPaths] = useState<RightsPath[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;                                  // a late response for the previous agent must not overwrite the current one
    Api.rights(agent).then((p) => { if (alive) { setPaths(p); setSel(null); } }).catch(() => { if (alive) setPaths([]); });
    return () => { alive = false; };
  }, [agent]);
  const g = useMemo(() => rightsGraph(agent, paths, sel, names), [agent, paths, sel, names]);
  const n = (id: string) => names.get(id) ?? id;
  return (
    <div className="rights" data-testid="rights">
      <div className="side-list">
        <label>Agent <select value={agent} onChange={(e) => setAgent(e.target.value)} data-testid="rights-agent">
          {(topology?.agents ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        <h4>Readable memories ({paths.length})</h4>
        <p className="muted">Path: SUPERVISES* then a single terminal relationship. Click to highlight.</p>
        <ul className="plain">
          {paths.map((p) => (
            <li key={p.memoryId}><button className={`link ${sel === p.memoryId ? "on" : ""}`} onClick={() => setSel(p.memoryId)} data-testid="memory-path">
              {n(p.ownerId)} <small>{SHARE_LABEL[p.kind]}</small></button></li>))}
        </ul>
      </div>
      <Canvas nodes={g.nodes} rels={g.rels} />
    </div>
  );
}

function KgExplorer() {
  const { topology } = useApp();
  const [kg, setKg] = useState("produit");
  const [key, setKey] = useState("PRT-0045");
  const [data, setData] = useState<KgNeighborhood | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);
  const go = (k = key, g = kg) => {
    const mine = ++seq.current;                        // only the last request updates the display
    setErr(null);
    Api.kg(g, k).then((d) => { if (mine === seq.current) setData(d); }).catch((e) => { if (mine === seq.current) { setData(null); setErr(String(e)); } });
  };
  useEffect(() => go(), []);
  const graph = useMemo(() => (data ? kgGraph(data) : null), [data]);
  return (
    <div className="kg" data-testid="kg">
      <form className="row" onSubmit={(e) => { e.preventDefault(); go(); }}>
        <select value={kg} onChange={(e) => { setKg(e.target.value); setKey(e.target.value === "produit" ? "PRT-0045" : "TSK-05"); }} data-testid="kg-select">
          {(topology?.kgs ?? []).map((k) => <option key={k.id} value={k.id}>KG {k.id}</option>)}</select>
        <input value={key} onChange={(e) => setKey(e.target.value)} aria-label="Entity key" data-testid="kg-key" />
        <button type="submit">Explore</button>
        <span className="muted">Retired parts in grey; tests in blue.</span>
      </form>
      {err && <p className="error">{err}</p>}
      {graph && <Canvas nodes={graph.nodes} rels={graph.rels} />}
    </div>
  );
}
