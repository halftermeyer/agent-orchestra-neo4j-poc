export const PERFORMATIVE_FR: Record<string, string> = {
  inform: "Information", request: "Demande", query: "Question", agree: "Accord", refuse: "Refus", propose: "Proposition",
  "accept-proposal": "Proposition acceptée", "reject-proposal": "Proposition refusée", confirm: "Confirmation", failure: "Échec", cancel: "Annulation",
};
export const SENDABLE = ["inform", "request", "query", "agree", "refuse"] as const;
export const KIND_FR: Record<string, string> = {
  incident: "Incident", "impact-request": "Demande d'impact", "analysis-request": "Demande d'analyse", "tests-report": "Rapport d'essais",
  "planning-impact": "Impact planning", "engineering-report": "Rapport d'ingénierie", "replacement-proposal": "Pièce proposée",
  "replacement-verdict": "Avis sur la pièce", "impact-summary": "Synthèse d'impact", "approval-decided": "Décision du comité",
  "bom-change": "Changement de BOM", "kg-raw": "Lot brut du KG", "commitment-due": "Engagement échu", "audit-scan": "Passage de l'auditeur",
  "chain-suspended": "Chaîne suspendue",
};
export const TOOL_FR: Record<string, string> = {
  send_message: "Envoi de message", set_status: "Statut", remember: "Mémorisation", recall: "Rappel mémoire", query_kg: "Requête KG",
  commit: "Engagement", request_approval: "Demande de validation", cpa_simulate: "Chemin critique", suspend_chain: "Suspension de chaîne",
  quarantine_agent: "Quarantaine", launch_modification: "Lancement de la modification",
};
export const STATUS_FR: Record<string, string> = {
  working: "en cours", completed: "terminé", failed: "échec", canceled: "annulé", "input-required": "en attente d'une décision",
  open: "ouvert", fulfilled: "soldé", fired: "déclenchée", scheduled: "planifiée", approved: "approuvée", rejected: "refusée", pending: "en attente",
};
export const SHARE_FR: Record<string, string> = { memory: "mémoire propre ou supervisée", share: "partage direct", message: "mémoire jointe à un message" };
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
