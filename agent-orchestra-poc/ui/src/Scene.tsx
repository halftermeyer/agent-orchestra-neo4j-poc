import { AnimatePresence, motion } from "framer-motion";
import { Avatar } from "./Avatar";
import { MODE_LABEL } from "./avatarState";
import { useApp } from "./store";
import type { Agent } from "./types";

const POS: Record<string, [number, number]> = {
  "ing-qualite": [120, 140], "comite-1": [460, 130], "comite-2": [640, 130], "comite-3": [820, 130], "chef-projet": [1150, 140],
  qualite: [200, 360], coordinateur: [640, 360], "interpreteur-bom": [1070, 360],
  ingenierie: [400, 570], essais: [600, 570], planification: [800, 570], "pont-kg": [1070, 580], auditeur: [190, 590],
};
const TOPICS: Record<string, [number, number, string]> = {
  incidents: [330, 250, "incidents"], "kg.produit.raw": [900, 470, "kg.produit.raw"], "produit.bom-changes": [930, 250, "produit.bom-changes"],
};

const stationPos = (id: string, i: number): [number, number] => POS[id] ?? [150 + (i % 6) * 180, 700];
const mailbox = (p: [number, number]): [number, number] => [p[0] - 62, p[1] + 30];

export function Scene() {
  const { topology, live, flights, names, follow } = useApp();
  if (!topology) return <p className="muted">Chargement de la scène…</p>;
  const agents = topology.agents;
  const where = (id: string): [number, number] => {
    if (TOPICS[id]) return [TOPICS[id][0], TOPICS[id][1]];
    const i = agents.findIndex((a) => a.id === id);
    return mailbox(stationPos(id, Math.max(i, 0)));
  };
  return (
    <div className="scene-wrap">
      <svg viewBox="0 0 1280 740" className="scene" role="img" aria-label="Plateau des agents et des humains" data-testid="scene" data-follow={follow ?? ""}>
        <defs>
          <pattern id="floor" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#E7EBF1" strokeWidth="1" /></pattern>
        </defs>
        <rect width="1280" height="740" rx="18" fill="#F7F9FC" /><rect width="1280" height="740" rx="18" fill="url(#floor)" />
        <Zone x={380} y={50} w={540} h={170} label="Salle du comité de modification" />
        <Zone x={60} y={60} w={140} h={150} label="Qualité (humain)" tiny />
        <Zone x={1080} y={60} w={140} h={150} label="Projet (humain)" tiny />
        {Object.entries(TOPICS).map(([id, [x, y, label]]) => (
          <g key={id} data-testid={`topic-${id}`} transform={`translate(${x} ${y})`}>
            <rect x="-62" y="-14" width="124" height="28" rx="8" fill="#EFEAFB" stroke="#B8A9E8" /><text textAnchor="middle" y="4" fontSize="11" fill="#5B4AA0">{label}</text>
          </g>
        ))}
        {agents.map((a, i) => <Station key={a.id} agent={a} pos={stationPos(a.id, i)} name={names.get(a.id) ?? a.id} pending={live[a.id]?.pending ?? 0} facts={live[a.id]?.facts ?? 0} />)}
        <AnimatePresence>
          {flights.map((f) => {
            const [sx, sy] = where(f.from.startsWith("routine:") || f.from === "gateway" ? "auditeur" : f.from), [tx, ty] = where(f.to);
            const [fx, fy] = f.from.startsWith("routine:") || !agents.some((a) => a.id === f.from) ? [tx, ty - 90] : [sx, sy];
            return (
              <motion.g key={f.id} data-testid="envelope" initial={{ x: fx, y: fy - 30, opacity: 1, scale: 0.9 }} animate={{ x: tx, y: ty - 6, scale: 1.1 }} exit={{ opacity: 0 }} transition={{ duration: 1.1, ease: "easeInOut" }}>
                <rect x="-11" y="-8" width="22" height="16" rx="2.5" fill="#fff" stroke="#E0702B" strokeWidth="1.8" /><path d="M-11 -8 L0 2 L11 -8" fill="none" stroke="#E0702B" strokeWidth="1.8" />
              </motion.g>
            );
          })}
        </AnimatePresence>
      </svg>
      <ul className="legend" aria-label="Légende des états">
        {Object.entries(MODE_LABEL).map(([k, v]) => <li key={k}><span className={`dot dot-${k}`} />{v}</li>)}
      </ul>
    </div>
  );
}

function Zone({ x, y, w, h, label, tiny }: { x: number; y: number; w: number; h: number; label: string; tiny?: boolean }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="16" fill="#EEF2F8" stroke="#D5DCE8" strokeDasharray="6 5" />
      <text x={x + 14} y={y + h - 10} fontSize={tiny ? 10.5 : 12} fill="#7B8798" fontWeight="600">{label}</text>
    </g>
  );
}

function Station({ agent, pos, name, pending, facts }: { agent: Agent; pos: [number, number]; name: string; pending: number; facts: number }) {
  const { stateOf, follow } = useApp();
  const s = stateOf(agent.id);
  const dim = !!follow && follow !== agent.id;
  const [x, y] = pos;
  return (
    <g transform={`translate(${x} ${y})`} data-testid={`station-${agent.id}`} data-followed={follow === agent.id ? "true" : "false"} opacity={dim ? 0.3 : 1}>
      {follow === agent.id && <rect x="-92" y="-62" width="184" height="196" rx="18" fill="none" stroke="#F0562A" strokeWidth="3" strokeDasharray="8 5" />}
      <rect x="-78" y="26" width="156" height="58" rx="12" fill="#fff" stroke="#D5DCE8" />
      <rect x="-60" y="22" width="120" height="10" rx="5" fill="#E4D6C4" />
      <Avatar agent={agent} state={s} />
      <text y="106" textAnchor="middle" fontSize="13" fontWeight="650" fill="#1F2A3C">{name}</text>
      <text y="121" textAnchor="middle" fontSize="10.5" fill="#7B8798" data-testid={`mode-${agent.id}`}>{MODE_LABEL[s.mode]}{agent.quarantined ? " · quarantaine" : ""}</text>
      <Mailbox pulse={s.mode === "woken" ? s.pulse : 0} pending={pending} id={agent.id} />
      <Shelf pulse={s.mode === "learning" ? s.pulse : 0} facts={facts} />
    </g>
  );
}

function Mailbox({ pulse, pending, id }: { pulse: number; pending: number; id: string }) {
  return (
    <g transform="translate(-62 30)" data-testid={`mailbox-${id}`} data-blink={pulse}>
      <motion.rect key={pulse} x="-14" y="-10" width="28" height="22" rx="4" fill="#fff" stroke="#6B7686" strokeWidth="1.8"
        animate={pulse ? { fill: ["#FFE1D6", "#fff", "#FFE1D6", "#fff"], scale: [1, 1.18, 1, 1.12, 1] } : {}} transition={{ duration: 1.3 }} />
      <path d="M-14 -10 L0 3 L14 -10" fill="none" stroke="#6B7686" strokeWidth="1.5" />
      {pending > 0 && <g><circle cx="13" cy="-10" r="8" fill="#F0562A" /><text x="13" y="-6.5" fontSize="10" textAnchor="middle" fill="#fff" fontWeight="700">{pending}</text></g>}
    </g>
  );
}

function Shelf({ pulse, facts }: { pulse: number; facts: number }) {
  return (
    <g transform="translate(62 28)" data-testid="shelf">
      <rect x="-14" y="-16" width="28" height="30" rx="3" fill="#FBF1D4" stroke="#C8A94D" />
      <path d="M-14 -4 H14 M-14 7 H14" stroke="#C8A94D" />
      {[...Array(Math.min(facts, 5))].map((_, i) => <rect key={i} x={-11 + i * 5} y="-13" width="3.5" height="9" fill="#E8A33D" />)}
      <motion.circle key={pulse} cx="0" cy="0" r="12" fill="#F5B642" initial={{ opacity: 0 }} animate={pulse ? { opacity: [0, 0.7, 0] } : { opacity: 0 }} transition={{ duration: 1 }} />
      {facts > 0 && <text y="26" fontSize="10" textAnchor="middle" fill="#8A6D1B">{facts} fait{facts > 1 ? "s" : ""}</text>}
    </g>
  );
}
