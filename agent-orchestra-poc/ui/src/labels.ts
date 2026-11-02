export const PERFORMATIVE_LABEL: Record<string, string> = {
  inform: "Information", request: "Request", query: "Question", agree: "Agreement", refuse: "Refusal", propose: "Proposal",
  "accept-proposal": "Proposal accepted", "reject-proposal": "Proposal rejected", confirm: "Confirmation", failure: "Failure", cancel: "Cancellation",
};
export const SENDABLE = ["inform", "request", "query", "agree", "refuse"] as const;
export const KIND_LABEL: Record<string, string> = {
  incident: "Incident", "impact-request": "Impact request", "analysis-request": "Analysis request", "tests-report": "Test report",
  "planning-impact": "Schedule impact", "engineering-report": "Engineering report", "replacement-proposal": "Proposed part",
  "replacement-verdict": "Verdict on the part", "impact-summary": "Impact summary", "approval-decided": "Committee decision",
  "bom-change": "BOM change", "kg-raw": "Raw KG batch", "commitment-due": "Commitment due", "audit-scan": "Auditor sweep",
  "chain-suspended": "Chain suspended", "modification-launched": "Modification launched",
};
export const TOOL_LABEL: Record<string, string> = {
  send_message: "Send message", set_status: "Status", remember: "Remember", recall: "Recall memory", query_kg: "KG query",
  commit: "Commitment", request_approval: "Approval request", cpa_simulate: "Critical path", suspend_chain: "Chain suspension",
  quarantine_agent: "Quarantine", launch_modification: "Modification launch",
};
export const STATUS_LABEL: Record<string, string> = {
  working: "in progress", completed: "completed", failed: "failed", canceled: "canceled", "input-required": "waiting for a decision",
  open: "open", fulfilled: "fulfilled", fired: "fired", scheduled: "scheduled", approved: "approved", rejected: "rejected", pending: "pending",
};
export const SHARE_LABEL: Record<string, string> = { memory: "own or supervised memory", share: "direct share", message: "memory attached to a message" };
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
