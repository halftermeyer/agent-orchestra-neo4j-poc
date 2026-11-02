import { motion } from "framer-motion";
import type { Agent } from "./types";
import { MODE_LABEL, type AvatarState } from "./avatarState";

const hue = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
const ROLE_COLOR: Record<string, string> = { coordinator: "#3B6FD4", specialist: "#4C8EDA", bridge: "#3FA98B", interpreter: "#8B6FD6", auditor: "#E39A2D" };

/** Avatars: original SVG creations (robots for software agents, silhouettes for humans). */
export function Avatar({ agent, state }: { agent: Agent; state: AvatarState }) {
  const base = agent.person ? `hsl(${hue(agent.id)} 55% 62%)` : ROLE_COLOR[agent.role ?? ""] ?? "#4C8EDA";
  const waiting = state.mode === "waiting";
  const error = state.mode === "error";
  const fill = error ? "#E04646" : base;
  const anim =
    state.mode === "woken" ? { y: [0, -16, 0], rotate: [0, -7, 7, 0] }
    : state.mode === "error" ? { x: [-7, 7, -5, 5, 0] }
    : state.mode === "sending" ? { x: [0, 8, 0] }
    : state.mode === "thinking" ? { rotate: [-2, 2, -2] }
    : state.mode === "tool" ? { y: [0, -3, 0] }
    : { y: [0, -2.5, 0], scaleY: [1, 1.025, 1] };                      // slow breathing
  const dur = state.mode === "idle" || state.mode === "waiting" ? 3.6 : state.mode === "woken" ? 0.7 : state.mode === "error" ? 0.5 : state.mode === "sending" ? 0.6 : 1.6;
  const loop = ["idle", "waiting", "thinking", "tool"].includes(state.mode);
  return (
    <g data-testid={`avatar-${agent.id}`} data-state={state.mode} data-label={MODE_LABEL[state.mode]} style={{ filter: waiting ? "grayscale(0.85)" : undefined, opacity: waiting ? 0.7 : 1 }}>
      <motion.g key={`${state.mode}-${state.pulse}`} animate={anim} transition={{ duration: dur, repeat: loop ? Infinity : 0, ease: "easeInOut" }} style={{ transformBox: "fill-box", transformOrigin: "50% 100%" }}>
        {agent.person ? (
          <>
            <path d="M-26 40 Q-26 8 0 8 Q26 8 26 40 Z" fill={fill} />
            <circle cx="0" cy="-12" r="19" fill="#F3D3B8" />
            <path d={`M-19 -14 Q-16 -34 0 -33 Q16 -34 19 -14 Q8 -24 -19 -14 Z`} fill={`hsl(${hue(agent.id + "x")} 35% 28%)`} />
            <circle cx="-6" cy="-10" r="2" fill="#333" /><circle cx="6" cy="-10" r="2" fill="#333" />
            <path d="M-5 -2 Q0 2 5 -2" stroke="#8A4B3A" strokeWidth="1.6" fill="none" />
          </>
        ) : (
          <>
            <line x1="0" y1="-38" x2="0" y2="-26" stroke="#555" strokeWidth="2.5" />
            <circle cx="0" cy="-40" r="4" fill={state.busy ? "#F5B642" : "#9AA4B2"} />
            <rect x="-28" y="-26" width="56" height="42" rx="12" fill={fill} />
            <rect x="-20" y="-16" width="40" height="18" rx="9" fill="#0F2A4A" />
            <circle cx="-8" cy="-7" r="3.6" fill={error ? "#FF8A8A" : "#8FE3FF"} /><circle cx="8" cy="-7" r="3.6" fill={error ? "#FF8A8A" : "#8FE3FF"} />
            <rect x="-22" y="16" width="44" height="22" rx="7" fill={fill} opacity="0.88" />
            <rect x="-10" y="22" width="20" height="4" rx="2" fill="#fff" opacity="0.55" />
          </>
        )}
      </motion.g>
      {state.mode === "tool" && <ToolBadge tool={state.tool} />}
      {waiting && <Hourglass />}
      {state.note ? <Bubble text={state.note} /> : state.mode === "thinking" && <Bubble text={state.bubble} />}
      {state.mode === "learning" && <Spark key={state.pulse} />}
      {state.mode === "woken" && <text x="30" y="-34" fontSize="22" fontWeight="700" fill="#F0562A">!</text>}
    </g>
  );
}

function Bubble({ text }: { text?: string }) {
  const t = text && text.length > 46 ? text.slice(0, 44) + "…" : text;
  const w = Math.max(44, Math.min(230, (t?.length ?? 3) * 6.4 + 18));
  return (
    <g data-testid="bubble" transform="translate(-6 -68)">
      <rect x={-w / 2 + 16} y="-24" width={w} height="26" rx="13" fill="#fff" stroke="#C8D0DC" />
      <path d="M2 2 L10 10 L14 2 Z" fill="#fff" stroke="#C8D0DC" />
      <rect x="1" y="1" width="14" height="3" fill="#fff" />
      {t ? <text x="16" y="-6" fontSize="11.5" textAnchor="middle" fill="#2B3547">{t}</text> : (
        <g>{[0, 1, 2].map((i) => <motion.circle key={i} cx={8 + i * 8} cy="-11" r="2.6" fill="#7B8798" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }} />)}</g>
      )}
    </g>
  );
}

function ToolBadge({ tool }: { tool?: string }) {
  return (
    <g data-testid="tool-badge" transform="translate(40 -10)">
      <circle r="17" fill="#fff" stroke="#C8D0DC" />
      <motion.g animate={{ rotate: 360 }} transition={{ duration: 2.4, repeat: Infinity, ease: "linear" }}>
        <path d="M0 -9 L2.4 -5 L7 -7 L6 -2.4 L10 0 L6 2.4 L7 7 L2.4 5 L0 9 L-2.4 5 L-7 7 L-6 2.4 L-10 0 L-6 -2.4 L-7 -7 L-2.4 -5 Z" fill="#4C8EDA" />
        <circle r="3" fill="#fff" />
      </motion.g>
      <rect x="-22" y="21" width="44" height="5" rx="2.5" fill="#E3E8F0" />
      <motion.rect x="-22" y="21" height="5" rx="2.5" fill="#4C8EDA" initial={{ width: 0 }} animate={{ width: [0, 44] }} transition={{ duration: 1.6, repeat: Infinity }} />
      <text y="40" fontSize="10" textAnchor="middle" fill="#4A5568">{tool}</text>
    </g>
  );
}

function Hourglass() {
  return (
    <motion.g data-testid="hourglass" transform="translate(34 -30)" animate={{ rotate: [0, 0, 180, 180] }} transition={{ duration: 4, repeat: Infinity, times: [0, 0.45, 0.55, 1] }}>
      <path d="M-8 -11 H8 L2 0 L8 11 H-8 L-2 0 Z" fill="#fff" stroke="#6B7686" strokeWidth="1.8" />
      <path d="M-4 8 H4 L0 3 Z" fill="#E8A33D" />
    </motion.g>
  );
}

function Spark() {
  return (
    <motion.g initial={{ x: 0, y: -10, opacity: 1, scale: 0.6 }} animate={{ x: 58, y: 18, opacity: [1, 1, 0], scale: [0.6, 1.3, 0.8] }} transition={{ duration: 1.3 }}>
      <path d="M0 -9 L2.5 -2.5 L9 0 L2.5 2.5 L0 9 L-2.5 2.5 L-9 0 L-2.5 -2.5 Z" fill="#F5B642" />
    </motion.g>
  );
}
