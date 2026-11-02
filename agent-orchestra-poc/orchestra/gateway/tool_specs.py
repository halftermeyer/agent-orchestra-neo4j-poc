"""Déclarations d'outils exposées au LLM. Jamais d'`agentId` en argument : il vient du jeton (règle 3)."""
S = lambda **props: {"type": "object", "properties": props, "required": list(props)}
STR = {"type": "string"}

TOOL_SPECS = {
    "send_message": {"description": "Send a message to one or more allowed inboxes.",
                     "parameters": {"type": "object", "required": ["to", "performative", "body"], "properties": {
                         "to": {"type": "array", "items": STR}, "performative": STR, "body": STR,
                         "attach_memory": {"type": "boolean"}, "payload": {"type": "object"}}}},
    "set_status": {"description": "Publish a short sentence describing what you are doing.", "parameters": S(text=STR)},
    "remember": {"description": "Store a fact in your memory.",
                 "parameters": {"type": "object", "required": ["statement"], "properties": {
                     "statement": STR, "confidence": {"type": "number"},
                     "about": {"type": "array", "items": {"type": "object", "properties": {"db": STR, "key": STR, "label": STR}}}}}},
    "recall": {"description": "Search the memories you are allowed to read.", "parameters": S(query=STR)},
    "query_kg": {"description": "Query a knowledge graph with a query template.",
                 "parameters": {"type": "object", "required": ["kg", "template"], "properties": {
                     "kg": STR, "template": STR, "params": {"type": "object"}}}},
    "commit": {"description": "Make a commitment to another agent (a timer will remind you when it is due), "
                              "or settle an existing commitment with `fulfills`.",
               "parameters": {"type": "object", "properties": {
                   "to": STR, "description": STR, "due_in_minutes": {"type": "integer"}, "fulfills": STR}}},
    "request_approval": {"description": "Ask the committee to approve an irreversible action (e.g. launch_modification). "
                                         "The arguments frozen here are the ones that will be executed if approval is obtained.",
                         "parameters": {"type": "object", "required": ["tool", "description"], "properties": {
                             "tool": STR, "description": STR, "part_id": STR, "replacement_id": STR}}},
    "launch_modification": {"description": "Launch the approved modification (writes the new version into the Product KG). "
                                           "Usable only after an `approved` approval.",
                            "parameters": S(approval_id=STR)},
    "cpa_simulate": {"description": "Simulate a delay on the schedule (critical path).",
                     "parameters": {"type": "object", "required": ["task_id", "delay_days"],
                                    "properties": {"task_id": STR, "delay_days": {"type": "integer"}}}},
    "suspend_chain": {"description": "Suspend a causal chain.", "parameters": S(chain_id=STR, reason=STR)},
    "quarantine_agent": {"description": "Put an agent in quarantine.", "parameters": S(target=STR, reason=STR)},
}
