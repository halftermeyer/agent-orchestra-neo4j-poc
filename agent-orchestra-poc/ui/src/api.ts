import type {
  AgentCard, AgentLive, ChatMessage, DemoUser, Incident, KgNeighborhood, Me, ModelsStatus, PendingApproval, RecordingInfo, ReplayDoc, RightsPath,
  RunInfo, Session, StreamEvent, TimelineItem, Topology,
} from "./types";

const BASE = "/api";
const KEY = "orchestra.session";

export function loadSession(): Session | null {
  const raw = sessionStorage.getItem(KEY);   // sessionStorage : jeton de démonstration seulement, jamais de clé LLM
  return raw ? (JSON.parse(raw) as Session) : null;
}
export function saveSession(s: Session | null) {
  if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY);
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(`${status} ${detail}`); }
}

async function call<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const t = token ?? loadSession()?.token;
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "content-type": "application/json", ...(t ? { authorization: `Bearer ${t}` } : {}), ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail ?? j.error ?? detail; } catch { /* corps non JSON */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}
const get = <T,>(p: string) => call<T>(p);
const post = <T,>(p: string, body?: unknown) => call<T>(p, { method: "POST", body: JSON.stringify(body ?? {}) });

export const Api = {
  users: () => get<{ users: DemoUser[] }>("/demo/users").then((r) => r.users),
  login: (userId: string) => post<Session>("/demo/login", { userId }),
  me: () => get<Me>("/me"),
  incidents: () => get<{ incidents: Incident[] }>("/demo/incidents").then((r) => r.incidents),
  chat: () => get<{ messages: ChatMessage[] }>("/chat/messages").then((r) => r.messages),
  send: (b: { to: string[]; performative: string; body: string; chainId?: string; payload?: Record<string, unknown> }) =>
    post<{ id: string; chainId: string }>("/messages", b),
  approvals: () => get<{ approvals: PendingApproval[] }>("/approvals").then((r) => r.approvals),
  vote: (id: string, decision: "approve" | "reject", comment?: string) =>
    post<{ status: string }>(`/approvals/${id}/votes`, { decision, comment }),
  topology: () => get<Topology>("/graph/topology"),
  state: () => get<{ agents: AgentLive[] }>("/graph/state").then((r) => r.agents),
  card: (id: string) => get<AgentCard>(`/graph/agent/${encodeURIComponent(id)}`),
  rights: (id: string) => get<{ memories: RightsPath[] }>(`/graph/rights/${encodeURIComponent(id)}`).then((r) => r.memories),
  kg: (kg: string, key: string) => get<KgNeighborhood>(`/graph/kg/${kg}/neighborhood?key=${encodeURIComponent(key)}`),
  timeline: (hours = 24) => get<{ items: TimelineItem[] }>(`/timeline?hours=${hours}`).then((r) => r.items),
  runs: () => get<{ runs: RunInfo[] }>("/replay/runs").then((r) => r.runs),
  recordings: () => get<{ recordings: RecordingInfo[] }>("/replay/recordings").then((r) => r.recordings),
  recording: (slug: string) => get<ReplayDoc>(`/replay/recordings/${encodeURIComponent(slug)}`),
  // reconstruit le flux depuis le graphe : mêmes événements normalisés qu'en direct
  replayEvents: (q: { runId?: string; since?: string }) =>
    get<{ events: StreamEvent[] }>(`/replay/events?${new URLSearchParams(q as Record<string, string>)}`).then((r) => r.events),
  models: () => get<ModelsStatus>("/settings/models"),
  // écriture seule : la clé n'est jamais relue, seuls les 4 derniers caractères et la date sont réaffichés
  setKey: (apiKey: string) => call<ModelsStatus>("/settings/models/key", { method: "PUT", body: JSON.stringify({ apiKey }) }),
  deleteKey: () => call<ModelsStatus>("/settings/models/key", { method: "DELETE" }),
  testKey: (apiKey?: string) => post<{ ok: boolean; models: string[]; error?: string }>("/settings/models/test", apiKey ? { apiKey } : {}),
  selectModel: (model: string) => call<{ model: string }>("/settings/models/selection", { method: "PUT", body: JSON.stringify({ model }) }),
};
