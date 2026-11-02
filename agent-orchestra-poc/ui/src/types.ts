export type EventType =
  | "woken" | "status" | "tool.start" | "tool.end" | "sent" | "learned" | "vote" | "waiting" | "idle" | "error";

/** Flux normalisé : identique en direct et (phase 6) en relecture depuis le graphe. */
export interface StreamEvent {
  t: string;
  type: EventType;
  actor: string | null;
  target: string | null;
  payload: Record<string, unknown>;
}

export interface Session { token: string; kind: "user" | "admin"; id: string; name: string }
export interface DemoUser { id: string; name: string; title?: string; admin?: boolean }

export interface Agent {
  id: string; name: string; person: boolean; role: string | null; title: string | null; quarantined: boolean;
  kind: "llm" | "rule" | null; model: string | null; inbox: string | null;
}
export interface Edge { from: string; to: string }
export interface RoutineInfo {
  id: string; owner: string; trigger: string; cron: string | null; enabled: boolean; nextRunAt: string | null;
  runAt: string | null; deliversTo: string | null; listensTo: string | null;
}
export interface Topology {
  agents: Agent[]; inboxes: { id: string; topic: boolean }[]; supervises: Edge[]; canSendTo: Edge[]; audits: Edge[];
  canQuery: Edge[]; kgs: { id: string; dbName: string }[]; routines: RoutineInfo[];
}
export interface AgentLive {
  id: string; busy: boolean; lastStatus: { text: string; at: string } | null; pending: number; commitments: number;
  inputRequired: number; facts: number;
}
export interface AgentCard {
  id: string; name: string; person: boolean; role: string | null; title: string | null; quarantined: boolean;
  version: { id: string; kind: string; model: string | null; prompt: string; createdAt: string } | null;
  versionHistory: string[];
  mandate: { purpose: string; scope: string; successCriteria: string } | null;
  tools: { name: string; effect: string; approval: string }[];
  kgs: string[]; supervisors: string[]; subordinates: string[]; audits: string[];
  routines: { id: string; trigger: string; cron: string | null; enabled: boolean }[];
  commitments: { id: string; to: string; description: string; dueAt: string }[];
  facts: number; statuses: { text: string; at: string }[]; toolCalls: { tool: string; status: string; at: string }[];
}
export interface RightsPath { memoryId: string; ownerId: string; kind: "memory" | "share" | "message"; nodes: string[]; rels: string[]; asOf: string }
export interface KgNeighborhood {
  kg: string; key: string;
  nodes: { id: string; name: string; labels: string[]; retired: boolean }[];
  rels: { id: string; from: string; to: string; type: string }[];
}
export interface ChatMessage {
  id: string; from: string; performative: string; body: string | null; payload: Record<string, unknown> | null; chainId: string;
  createdAt: string; direction: "in" | "out"; to: string[]; hasSharedMemory: boolean;
}
export interface PendingApproval {
  id: string; policy: string; quorum: number; size: number; requestedBy: string; requestedAt: string;
  args: { part_id?: string; replacement_id?: string; description?: string }; votes: number; chainId: string | null;
}
export interface Incident { id: string; kind: string; componentId: string; severity: string; description: string; observedAt: string }
export interface TimelineItem {
  t: string; end?: string | null; kind: "tool" | "vote" | "routine" | "routine-next" | "commitment";
  actor: string | null; label: string; status: string; target?: string; ref?: string;
}
export interface ModelsStatus { configured: boolean; source: "ui" | "env" | null; last4: string | null; updatedAt: string | null; provider: string; model: string | null }
export interface Me { id: string; name: string; canSendTo: string[]; kgs: string[]; inboxes: string[] }
