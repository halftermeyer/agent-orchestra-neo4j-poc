"""Déclarations d'outils exposées au LLM. Jamais d'`agentId` en argument : il vient du jeton (règle 3)."""
S = lambda **props: {"type": "object", "properties": props, "required": list(props)}
STR = {"type": "string"}

TOOL_SPECS = {
    "send_message": {"description": "Envoie un message à une ou plusieurs inbox autorisées.",
                     "parameters": {"type": "object", "required": ["to", "performative", "body"], "properties": {
                         "to": {"type": "array", "items": STR}, "performative": STR, "body": STR,
                         "attach_memory": {"type": "boolean"}, "payload": {"type": "object"}}}},
    "set_status": {"description": "Publie une phrase courte décrivant ce que tu fais.", "parameters": S(text=STR)},
    "remember": {"description": "Enregistre un fait dans ta mémoire.",
                 "parameters": {"type": "object", "required": ["statement"], "properties": {
                     "statement": STR, "confidence": {"type": "number"},
                     "about": {"type": "array", "items": {"type": "object", "properties": {"db": STR, "key": STR, "label": STR}}}}}},
    "recall": {"description": "Cherche dans les mémoires que tu as le droit de lire.", "parameters": S(query=STR)},
    "query_kg": {"description": "Interroge un graphe de connaissance avec un modèle de requête.",
                 "parameters": {"type": "object", "required": ["kg", "template"], "properties": {
                     "kg": STR, "template": STR, "params": {"type": "object"}}}},
    "commit": {"description": "Prends un engagement envers un autre agent (une minuterie te relancera à l'échéance), "
                              "ou solde un engagement existant avec `fulfills`.",
               "parameters": {"type": "object", "properties": {
                   "to": STR, "description": STR, "due_in_minutes": {"type": "integer"}, "fulfills": STR}}},
    "request_approval": {"description": "Demande la validation du comité pour une action irréversible (ex. launch_modification). "
                                         "Les arguments figés ici sont ceux qui seront exécutés si la validation est obtenue.",
                         "parameters": {"type": "object", "required": ["tool", "description"], "properties": {
                             "tool": STR, "description": STR, "part_id": STR, "replacement_id": STR}}},
    "launch_modification": {"description": "Lance la modification approuvée (écrit la nouvelle version dans le KG Produit). "
                                           "Utilisable seulement après une validation `approved`.",
                            "parameters": S(approval_id=STR)},
    "cpa_simulate": {"description": "Simule un retard sur le planning (chemin critique).",
                     "parameters": {"type": "object", "required": ["task_id", "delay_days"],
                                    "properties": {"task_id": STR, "delay_days": {"type": "integer"}}}},
    "suspend_chain": {"description": "Suspend une chaîne causale.", "parameters": S(chain_id=STR, reason=STR)},
    "quarantine_agent": {"description": "Met un agent en quarantaine.", "parameters": S(target=STR, reason=STR)},
}
