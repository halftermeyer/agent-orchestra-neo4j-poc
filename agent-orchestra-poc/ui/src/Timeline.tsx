import { useCallback, useEffect, useMemo, useState } from "react";
import { Api } from "./api";
import { STATUS_LABEL, TOOL_LABEL, fmtDateTime } from "./labels";
import { useApp, useOnEvents } from "./store";
import type { TimelineItem } from "./types";

const KINDS: Record<string, { label: string; color: string }> = {
  tool: { label: "Tool call", color: "#4C8EDA" }, vote: { label: "Vote", color: "#2FA66A" }, routine: { label: "Routine fired", color: "#8B6FD6" },
  "routine-next": { label: "Upcoming routine", color: "#B8A9E8" }, commitment: { label: "Commitment", color: "#E8A33D" },
};
const HOURS = [1, 6, 24];
const W = 1100, LANE = 34, LEFT = 150;

/** Timeline: routines, tool calls, votes and commitments, one row per actor. */
export function Timeline() {
  const { names } = useApp();
  const [hours, setHours] = useState(1);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const load = useCallback(() => { Api.timeline(hours).then(setItems).catch(() => undefined); }, [hours]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useOnEvents(["tool.end", "vote", "waiting", "sent"], load, 600);

  const { lanes, t0, t1, ticks } = useMemo(() => {
    const now = Date.now();
    const lo = now - hours * 3600_000;
    const future = items.filter((i) => i.kind === "routine-next").map((i) => new Date(i.t).getTime());
    const hi = Math.max(now + 5 * 60_000, ...future.filter((f) => f < now + hours * 3600_000 / 4));
    const actors = [...new Set(items.map((i) => i.actor ?? "—"))].sort();
    const step = hours <= 1 ? 10 * 60_000 : hours <= 6 ? 3600_000 : 4 * 3600_000;
    const ticks: number[] = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
    return { lanes: actors, t0: lo, t1: hi, ticks };
  }, [items, hours]);
  const x = (iso: string | number) => LEFT + ((new Date(iso).getTime() - t0) / (t1 - t0)) * (W - LEFT - 20);
  const H = Math.max(120, lanes.length * LANE + 50);

  return (
    <div className="timeline" data-testid="timeline">
      <div className="toolbar">
        {HOURS.map((h) => <button key={h} className={`seg ${hours === h ? "on" : ""}`} onClick={() => setHours(h)}>{h} h</button>)}
        <ul className="legend inline">{Object.entries(KINDS).map(([k, v]) => <li key={k}><span className="dot" style={{ background: v.color }} />{v.label}</li>)}</ul>
        <span className="muted" data-testid="timeline-count">{items.length} items</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="tl" role="img" aria-label="Timeline of routines, tool calls, votes and commitments">
        {ticks.map((t) => <g key={t}><line x1={x(t)} x2={x(t)} y1="20" y2={H} stroke="#E7EBF1" /><text x={x(t)} y="14" fontSize="10" fill="#7B8798" textAnchor="middle">{new Date(t).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</text></g>)}
        <line x1={x(Date.now())} x2={x(Date.now())} y1="20" y2={H} stroke="#F0562A" strokeDasharray="4 3" /><text x={x(Date.now())} y={H - 4} fontSize="10" fill="#F0562A" textAnchor="middle">now</text>
        {lanes.map((a, i) => (
          <g key={a} transform={`translate(0 ${30 + i * LANE})`}>
            <rect x="0" y="-12" width={W} height={LANE - 2} fill={i % 2 ? "#FAFBFD" : "#fff"} />
            <text x="8" y="6" fontSize="12" fill="#2B3547" fontWeight="600">{names.get(a) ?? a}</text>
            {items.filter((it) => (it.actor ?? "—") === a).map((it, k) => <Mark key={k} it={it} x={x} />)}
          </g>
        ))}
      </svg>
    </div>
  );
}

function Mark({ it, x }: { it: TimelineItem; x: (v: string | number) => number }) {
  const c = KINDS[it.kind].color;
  const title = `${KINDS[it.kind].label} · ${TOOL_LABEL[it.label] ?? it.label} · ${STATUS_LABEL[it.status] ?? it.status} · ${fmtDateTime(it.t)}`;
  const x0 = x(it.t);
  const failed = it.status === "failed" || it.status === "rejected";
  if ((it.kind === "tool" || it.kind === "commitment") && it.end) {
    const w = Math.max(5, x(it.end) - x0);
    return <rect data-testid={`mark-${it.kind}`} x={x0} y="-4" width={w} height="12" rx="4" fill={failed ? "#E04646" : c} opacity={it.kind === "commitment" ? 0.45 : 0.9}><title>{title}</title></rect>;
  }
  if (it.kind === "vote") return <path data-testid="mark-vote" d={`M${x0} -5 l7 7 l-7 7 l-7 -7 Z`} fill={it.label === "approve" ? c : "#E04646"}><title>{title}</title></path>;
  if (it.kind === "routine-next") return <circle data-testid="mark-routine-next" cx={x0} cy="2" r="5" fill="none" stroke={c} strokeWidth="2"><title>{title}</title></circle>;
  return <circle data-testid={`mark-${it.kind}`} cx={x0} cy="2" r="5" fill={c}><title>{title}</title></circle>;
}
