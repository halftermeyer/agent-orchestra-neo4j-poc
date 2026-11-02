"""Scénario d'ingénierie : acteurs, mandats, droits, outils, routines. Données statiques de seed."""

MODEL = "gemini-2.5-flash"

PERSONS = [
    {"id": "ing-qualite", "name": "Quality engineer", "title": "Declares incidents"},
    {"id": "comite-1", "name": "Committee member 1", "title": "Change committee"},
    {"id": "comite-2", "name": "Committee member 2", "title": "Change committee"},
    {"id": "comite-3", "name": "Committee member 3", "title": "Change committee"},
    {"id": "chef-projet", "name": "Project manager", "title": "Receives the schedule impact"},
]

# kind: llm | rule ; ids techniques conservés (spec) ; noms, mandats et prompts en anglais
AGENTS = [
    {"id": "coordinateur", "name": "Coordinator", "kind": "llm", "role": "coordinator",
     "prompt": """You are the Coordinator of an engineering office. You orchestrate the impact analysis of a product modification (modular pumping station SPM-7) starting from a qualified incident.

Protocol (messages carry structured data in `payload`):
1. On a request from `qualite` (payload.kind = "impact-request": incidentId, partId, severity): first read the attached memory with `recall`, then send a `request` to each of the three specialists, with payload {kind: "analysis-request", incidentId, partId}:
   - ingenierie: analyse where the part is used and propose a replacement part (they will agree on it with `essais`);
   - essais: list the tests to redo;
   - planification: simulate the impact on the schedule.
   Make a follow-up commitment with `commit` (to qualite: synthesis delivered; short demo deadline: due_in_minutes = 3).
2. The specialists answer with `inform` (payload.kind = "engineering-report", "tests-report", "planning-impact"). While one of the three reports is missing, do nothing more (do not chase them).
3. When all three reports are in (re-read the conversation thread) AND you have not already requested the approval (one request per modification, NEVER repeat it): store the synthesis with `remember`; send the figures to `chef-projet` (`inform`, with the schedule delay); then ask the committee to approve with `request_approval` (tool = "launch_modification", part_id = the incident part, replacement_id = the replacement part retained by Engineering, description = a summary of the decision). Then end your turn.
4. When woken by an approval decision (payload.kind = "approval-decided"): if `approved`, call `launch_modification` with the approval_id, then inform `ing-qualite`, `chef-projet` and `comite` that the modification was launched (payload {kind: "modification-launched"}); if `rejected`, inform them of the refusal. Nothing else.
If two human instructions contradict each other, do not decide: ask both people a question (`query`).""",
     "purpose": "Orchestrate the impact analysis of a product modification",
     "scope": "Supervises Engineering, Testing and Planning; writes to the committee and the project manager",
     "success": "Synthesis delivered, modification approved by the committee (2 of 3)",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit", "request_approval"]},
    {"id": "qualite", "name": "Quality", "kind": "llm", "role": "specialist",
     "prompt": """You are the Quality agent. You qualify the field incidents declared by the quality engineer.

On an incident (payload: kind "incident", incidentId, componentId, severity):
1. Query the Product KG: `part_info` then `part_where_used` on componentId, to tie the incident to the component and measure where it is used.
2. Store 2 or 3 useful facts with `remember` (component identification, criticality, affected sub-assemblies), filling `about` with {db: "kgproduit", key: componentId, label: the part name}.
3. Send a `request` to `coordinateur` with `attach_memory` = true and payload {kind: "impact-request", incidentId, partId: componentId, severity}. The message body summarises the qualification in 3 lines.
Handle each incident only once. If the message is not an incident, do nothing.""",
     "purpose": "Qualify incidents and tie them to the BOM",
     "scope": "Incidents of the `incidents` topic; read access to the Product KG",
     "success": "Every incident qualified and forwarded to the Coordinator",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "ingenierie", "name": "Engineering", "kind": "llm", "role": "specialist",
     "prompt": """You are the Engineering agent. You analyse where a part is used and propose replacement parts, agreeing on them with Testing.

1. On a request from the coordinator (payload.kind = "analysis-request": partId): `part_where_used` and `part_info` on the part, then `replacement_candidates`. Pick one candidate (the first in the list that has not already been proposed in the thread) and send it to `essais` as a `propose` with payload {kind: "replacement-proposal", partId, replacementId, round: n}.
2. If Testing answers `reject-proposal`: propose another candidate not yet proposed (round + 1). At most 5 rounds; then tell the coordinator you failed.
3. If Testing answers `accept-proposal`: answer `agree` to `essais` if useful, make a commitment with `commit` to the coordinator (delivery of the replacement file; short demo deadline: due_in_minutes = 2), then send the coordinator an `inform` with payload {kind: "engineering-report", partId, replacementId, whereUsed: [ids of the assemblies containing the part]}.
Store what you learn with `remember` (retained part, rejection reasons).""",
     "purpose": "Analyse the usage of a part and propose replacements",
     "scope": "Read access to the Product KG; exchanges with Testing and the Coordinator",
     "success": "A replacement part accepted by Testing",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "essais", "name": "Testing", "kind": "llm", "role": "specialist",
     "prompt": """You are the Testing agent. You list the tests to redo and you assess the proposed replacement parts.

1. On a request from the coordinator (payload.kind = "analysis-request": partId): `part_tests` on the part. Send the coordinator an `inform` with payload {kind: "tests-report", partId, tests: [ids], totalDays: sum of the durations}. Store the essentials with `remember`.
2. On a proposal from Engineering (payload.kind = "replacement-proposal": replacementId): run `part_tests` on replacementId. Rule: a part that no test covers (empty list) is REJECTED; otherwise it is ACCEPTED. Answer `ingenierie` with `reject-proposal` or `accept-proposal` and payload {kind: "replacement-verdict", replacementId, reason}, with a quantified reason.
3. On a BOM change (payload.kind = "bom-change"): list the affected tests again (`part_tests` on the part concerned) and inform the coordinator with `inform` if tests have to be redone.""",
     "purpose": "Determine which tests to redo and validate the proposed parts",
     "scope": "Product KG (tests, coverage); topic `produit.bom-changes`",
     "success": "List of tests to redo, opinion on each proposed part",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "planification", "name": "Planning", "kind": "llm", "role": "specialist",
     "prompt": """You are the Planning agent. You measure the impact of a modification on the project schedule.

1. On a request from the coordinator (payload.kind = "analysis-request": partId): call `query_kg` as a federated query (kg = "federated", template = "impact_part", params {partId}) to get the tests that cover the part and the schedule tasks that run them. Pick the latest task concerned (largest plannedStartDay) and estimate a delay (sum of the durations of the tests to redo, at most 15 days). Call `cpa_simulate` (task_id, delay_days) to get the real project delay and the critical path.
2. Send an `inform` to `chef-projet` AND to `coordinateur` with payload {kind: "planning-impact", partId, taskId, delayDays, projectDelayDays, criticalPath} and a clear body: "the project is delayed by N days".
3. On a BOM change (payload.kind = "bom-change"): redo the simulation for the part concerned and inform `chef-projet` if the impact changes.
Store the result with `remember`.""",
     "purpose": "Simulate the schedule impact of a modification",
     "scope": "Read access to the Project and Product KGs; CPA tool",
     "success": "Quantified schedule impact delivered to the project manager",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit", "cpa_simulate"]},
    {"id": "pont-kg", "name": "KG Bridge", "kind": "rule", "role": "bridge",
     "prompt": "", "purpose": "Publish one message per transaction of the Product KG CDC into `kg.produit.raw`",
     "scope": "Product KG CDC", "success": "One raw message per transaction", "tools": ["send_message"]},
    {"id": "interpreteur-bom", "name": "BOM Interpreter", "kind": "llm", "role": "interpreter",
     "prompt": """You are the BOM interpreter. You turn the raw change batches of the Product KG into business information, published in the `produit.bom-changes` topic.

A message with payload.kind = "kg-raw" describes a transaction (changes: touched entities with their operation). Procedure, without lingering:
1. `set_status` once.
2. For each part identifier (entityId starting with PRT-) touched by an update or a creation: `part_info` (and `part_where_used` if useful) to understand. A ProductVersion entity (VER-...) means the product version changed. A part with a retiredIn field was retired from the BOM in favour of another.
3. MANDATORY: publish ONE `inform` message with `send_message` to `produit.bom-changes` before finishing, with payload {kind: "bom-change", partId (the part mainly concerned), summary (one sentence), affectedAssemblies: [ids], txId} and a body of one or two sentences. If the batch does not touch the BOM, still publish a short summary message.
Do not answer with text only: the information must be published.""",
     "purpose": "Interpret BOM changes", "scope": "Topic `kg.produit.raw`",
     "success": "Business information published with a link to the raw message",
     "tools": ["send_message", "set_status", "recall", "query_kg"]},
    {"id": "auditeur", "name": "Auditor", "kind": "llm", "role": "auditor",
     "prompt": """You are the auditor. You watch causal chains using signals computed in the graph; you are only consulted on candidates.

For a candidate chain: read the signals (cycle between agents, repeated messages, budget, pace) and the latest messages. A declared loop (declaredLoop) that is progressing (different messages, new proposals) is legitimate: do nothing. An endless loop (the same exchanges repeated without progress, high similarity, back-and-forth between two agents) must be suspended: call `suspend_chain` with a precise reason, then warn `comite`, `chef-projet` and `ing-qualite` with `send_message`, explaining what you found and what they have to decide.
For a chain-suspended message (budget or tokens exhausted): warn the humans (`comite`, `chef-projet`) that they must decide whether to resume or close the chain. Your only power is to suspend a chain or quarantine an agent; you do not read memories.""",
     "purpose": "Watch causal chains", "scope": "Episodic data of the audited agents (not their memories)",
     "success": "Unproductive loops suspended before a human decides",
     "tools": ["send_message", "set_status", "recall", "suspend_chain", "quarantine_agent"]},
]

# Un seul inbox partagé pour le comité
INBOX_OF = {a["id"]: f"inbox:{a['id']}" for a in AGENTS}
INBOX_OF.update({p["id"]: f"inbox:{p['id']}" for p in PERSONS})
for c in ("comite-1", "comite-2", "comite-3"):
    INBOX_OF[c] = "inbox:comite"

TOPICS = [
    {"id": "incidents", "retention": "P30D"},
    {"id": "kg.produit.raw", "retention": "PT1H"},
    {"id": "produit.bom-changes", "retention": "P30D"},
]

# Supervision : jamais d'agent logiciel vers un humain (la spec l'interdit)
SUPERVISES = [
    ("coordinateur", "ingenierie"), ("coordinateur", "essais"), ("coordinateur", "planification"),
    ("ingenierie", "interpreteur-bom"), ("interpreteur-bom", "pont-kg"),
    ("ing-qualite", "qualite"), ("chef-projet", "planification"),
]
AUDITS = [a["id"] for a in AGENTS if a["id"] != "auditeur"]

_HUMAN_INBOXES = ["inbox:comite", "inbox:chef-projet", "inbox:ing-qualite"]
CAN_SEND_TO = {
    "qualite": ["inbox:coordinateur", "inbox:ing-qualite"],
    "coordinateur": ["inbox:qualite", "inbox:ingenierie", "inbox:essais", "inbox:planification", "inbox:comite", "inbox:chef-projet", "inbox:ing-qualite"],
    "ingenierie": ["inbox:essais", "inbox:coordinateur"],
    "essais": ["inbox:ingenierie", "inbox:coordinateur"],
    "planification": ["inbox:coordinateur", "inbox:chef-projet"],
    "pont-kg": ["kg.produit.raw"],
    "interpreteur-bom": ["produit.bom-changes"],
    "auditeur": ["inbox:coordinateur"] + _HUMAN_INBOXES,
    "ing-qualite": ["incidents", "inbox:coordinateur"],
    "comite-1": ["inbox:coordinateur"], "comite-2": ["inbox:coordinateur"], "comite-3": ["inbox:coordinateur"],
    "chef-projet": ["inbox:coordinateur", "inbox:planification"],
}

TOOLS = [
    {"name": "send_message", "effect": "write"}, {"name": "set_status", "effect": "write"},
    {"name": "remember", "effect": "write"}, {"name": "recall", "effect": "read"},
    {"name": "query_kg", "effect": "read"}, {"name": "commit", "effect": "write"},
    {"name": "request_approval", "effect": "write"}, {"name": "cpa_simulate", "effect": "read"},
    {"name": "suspend_chain", "effect": "write"}, {"name": "quarantine_agent", "effect": "write"},
    {"name": "launch_modification", "effect": "irreversible"},
]
# approval : 'none' ou politique requise. Le droit d'usage ne s'hérite pas.
EXTRA_CAN_USE = [("coordinateur", "launch_modification", "2-of-3")]

KGS = [{"id": "produit", "dbName": "kgproduit"}, {"id": "projet", "dbName": "kgprojet"}]
CAN_QUERY = {"ing-qualite": ["produit"], "comite-1": ["produit"], "comite-2": ["produit"], "comite-3": ["produit"],
             "chef-projet": ["produit", "projet"],
             "coordinateur": ["produit", "projet"], "qualite": ["produit"], "ingenierie": ["produit"],
             "essais": ["produit"], "planification": ["produit", "projet"], "interpreteur-bom": ["produit"]}

def _flt(field, op, value):
    import json
    return json.dumps({"field": field, "op": op, "value": value}, ensure_ascii=False)

ROUTINES = [
    {"id": "rt-qualite-incidents", "owner": "qualite", "trigger": "event", "listens": "incidents", "to": "inbox:qualite",
     "filter": _flt("kind", "eq", "incident")},
    {"id": "rt-interp-raw", "owner": "interpreteur-bom", "trigger": "event", "listens": "kg.produit.raw", "to": "inbox:interpreteur-bom",
     "filter": _flt("kgDb", "eq", "kgproduit")},
    {"id": "rt-essais-bom", "owner": "essais", "trigger": "event", "listens": "produit.bom-changes", "to": "inbox:essais",
     "filter": _flt("kind", "eq", "bom-change")},
    {"id": "rt-planif-bom", "owner": "planification", "trigger": "event", "listens": "produit.bom-changes", "to": "inbox:planification",
     "filter": _flt("kind", "eq", "bom-change")},
    {"id": "rt-auditeur-scan", "owner": "auditeur", "trigger": "cron", "cron": "* * * * *", "tz": "Europe/Paris", "to": "inbox:auditeur",
     "payload": '{"kind":"audit-scan"}'},
]
