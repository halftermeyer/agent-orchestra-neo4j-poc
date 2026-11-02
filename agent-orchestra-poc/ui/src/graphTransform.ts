import type { Node, Relationship } from "@neo4j-nvl/base";
import type { Agent, KgNeighborhood, RightsPath, Topology } from "./types";

export const COLORS = {
  agent: "#4C8EDA", rule: "#6EC4A7", auditor: "#E8A33D", person: "#E86F8D", topic: "#9B8AD6", kg: "#5BB5A2", memory: "#F2C14E",
  other: "#B0B7C3", muted: "#D5DAE1", hot: "#F0562A", edge: "#8A94A6",
};

export function agentColor(a: Agent): string {
  if (a.person) return COLORS.person;
  if (a.role === "auditor") return COLORS.auditor;
  return a.kind === "rule" ? COLORS.rule : COLORS.agent;
}

const shortName = (n: string) => n.replace("Membre du comité", "Comité").replace("Ingénieur qualité", "Ing. qualité").replace("Chef de projet", "Chef projet");

export interface GraphOptions { showSend: boolean; showAudits: boolean; showKgAccess: boolean; showRoutines: boolean }

/** Topologie : un nœud par agent, par topic, par KG ; les inbox d'agent sont repliées sur leur propriétaire. */
export function topologyGraph(t: Topology, o: GraphOptions): { nodes: Node[]; rels: Relationship[] } {
  const owner = new Map<string, string[]>();
  for (const a of t.agents) if (a.inbox) owner.set(a.inbox, [...(owner.get(a.inbox) ?? []), a.id]);
  const nodes: Node[] = t.agents.map((a) => ({
    id: a.id, caption: shortName(a.name), color: agentColor(a), size: a.person ? 58 : 64, captionAlign: "center", captionSize: 2,
  } as Node));
  for (const i of t.inboxes) {
    const owners = owner.get(i.id) ?? [];
    if (i.topic) nodes.push({ id: i.id, caption: i.id, color: COLORS.topic, size: 30, captionAlign: "bottom", captionSize: 2 } as Node);
    else if (owners.length > 1) nodes.push({ id: i.id, caption: "Boîte partagée", color: COLORS.other, size: 30, captionAlign: "bottom", captionSize: 2 } as Node);
  }
  if (o.showKgAccess || t.kgs.length) for (const k of t.kgs) nodes.push({ id: `kg:${k.id}`, caption: `KG ${k.id}`, color: COLORS.kg, size: 48, captionAlign: "bottom", captionSize: 2 } as Node);

  const target = (inbox: string) => {
    const owners = owner.get(inbox) ?? [];
    return owners.length === 1 ? owners[0] : inbox;     // inbox d'un seul agent -> l'agent ; partagée ou topic -> son propre nœud
  };
  const rels: Relationship[] = [];
  for (const e of t.supervises) rels.push({ id: `sup:${e.from}>${e.to}`, from: e.from, to: e.to, caption: "SUPERVISES", color: COLORS.edge, width: 3 });
  if (o.showSend) for (const e of t.canSendTo) {
    const to = target(e.to);
    if (to !== e.from) rels.push({ id: `send:${e.from}>${to}`, from: e.from, to, caption: "", color: COLORS.muted, width: 1 });
  }
  if (o.showAudits) for (const e of t.audits) rels.push({ id: `aud:${e.from}>${e.to}`, from: e.from, to: e.to, caption: "AUDITS", color: COLORS.auditor, width: 1 });
  if (o.showKgAccess) for (const e of t.canQuery) rels.push({ id: `kgq:${e.from}>${e.to}`, from: e.from, to: `kg:${e.to}`, caption: "", color: COLORS.kg, width: 1 });
  if (o.showRoutines) for (const r of t.routines) if (r.listensTo) {
    const to = target(r.deliversTo ?? "");
    rels.push({ id: `rt:${r.id}`, from: r.listensTo, to, caption: r.id.replace(/^rt-/, ""), color: COLORS.topic, width: 2 });
  }
  const ids = new Set(nodes.map((n) => n.id));
  return { nodes, rels: rels.filter((r) => ids.has(r.from) && ids.has(r.to)) };
}

const NODE_KIND: Record<string, string> = { HAS_INBOX: "inbox", HAS_DAY: "jour", RECEIVED: "message", CAN_READ: "mémoire", HAS_MEMORY: "mémoire" };

/** Droits : l'union des chemins vers les mémoires lisibles ; le chemin choisi est surligné. */
export function rightsGraph(agentId: string, paths: RightsPath[], selected: string | null, names: Map<string, string>): { nodes: Node[]; rels: Relationship[] } {
  const nodes = new Map<string, Node>();
  const rels = new Map<string, Relationship>();
  const hotNodes = new Set(paths.find((p) => p.memoryId === selected)?.nodes ?? []);
  for (const p of paths) {
    const hot = p.memoryId === selected;
    p.nodes.forEach((id, i) => {
      if (!nodes.has(id)) {
        const isMemory = id.startsWith("mem:");
        const inner = i > 0 && !isMemory && !names.has(id);          // inbox, jour, message : nœuds intermédiaires
        nodes.set(id, {
          id, caption: isMemory ? `Mémoire · ${names.get(id.slice(4)) ?? id.slice(4)}` : names.get(id) ?? (id.length > 18 ? id.slice(0, 16) + "…" : id),
          color: isMemory ? COLORS.memory : inner ? COLORS.other : id === agentId ? COLORS.hot : COLORS.agent,
          size: id === agentId ? 38 : isMemory ? 26 : inner ? 14 : 30, captionAlign: "bottom",
        } as Node);
      }
    });
    p.rels.forEach((type, i) => {
      const id = `${p.nodes[i]}>${type}>${p.nodes[i + 1]}`;
      const existing = rels.get(id);
      rels.set(id, { id, from: p.nodes[i], to: p.nodes[i + 1], caption: type, color: hot || existing?.color === COLORS.hot ? COLORS.hot : COLORS.edge,
                     width: hot || existing?.width === 5 ? 5 : 2 });
    });
  }
  for (const n of nodes.values()) if (hotNodes.has(n.id) && n.id !== agentId) n.color = n.id.startsWith("mem:") ? COLORS.hot : n.color;
  return { nodes: [...nodes.values()], rels: [...rels.values()] };
}

export { NODE_KIND };

export function kgGraph(n: KgNeighborhood): { nodes: Node[]; rels: Relationship[] } {
  const color = (labels: string[]) => labels.includes("Test") ? COLORS.agent : labels.includes("Task") ? COLORS.topic : labels.includes("Resource") ? COLORS.person : COLORS.kg;
  return {
    nodes: n.nodes.map((x) => ({
      id: x.id, caption: `${x.id}`, color: x.retired ? COLORS.muted : color(x.labels), size: x.id === n.key ? 40 : 26,
      captionAlign: "bottom", selected: x.id === n.key,
    } as Node)),
    rels: n.rels.map((r) => ({ id: r.id, from: r.from, to: r.to, caption: r.type, color: COLORS.edge, width: 2 })),
  };
}

/** Flux : arêtes récemment utilisées, du plus chaud au plus froid. */
export function flowHeat(recent: { from: string; to: string; at: number }[], now: number, windowMs = 8000): Map<string, number> {
  const heat = new Map<string, number>();
  for (const r of recent) {
    const age = now - r.at;
    if (age > windowMs) continue;
    const k = `${r.from}>${r.to}`;
    heat.set(k, Math.max(heat.get(k) ?? 0, 1 - age / windowMs));
  }
  return heat;
}
