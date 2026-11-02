"""Scénario d'ingénierie : acteurs, mandats, droits, outils, routines. Données statiques de seed."""

MODEL = "gemini-2.5-flash"

PERSONS = [
    {"id": "ing-qualite", "name": "Ingénieur qualité", "title": "Déclare les incidents"},
    {"id": "comite-1", "name": "Membre du comité 1", "title": "Comité de modification"},
    {"id": "comite-2", "name": "Membre du comité 2", "title": "Comité de modification"},
    {"id": "comite-3", "name": "Membre du comité 3", "title": "Comité de modification"},
    {"id": "chef-projet", "name": "Chef de projet", "title": "Reçoit l'impact planning"},
]

# kind: llm | rule ; prompts courts, affinés en phase 4
AGENTS = [
    {"id": "coordinateur", "name": "Coordinateur", "kind": "llm", "role": "coordinator",
     "prompt": 'Tu es le Coordinateur d\'un bureau d\'études. Tu orchestres l\'analyse d\'impact d\'une modification produit (station de pompage modulaire SPM-7) à partir d\'un incident qualifié.\n\nProtocole (les messages portent des données structurées dans `payload`) :\n1. Sur une demande de Qualité (payload.kind = "impact-request" : incidentId, partId, severity) : consulte d\'abord la mémoire jointe avec `recall`, puis envoie une demande `request` à chacun des trois spécialistes, avec payload {kind: "analysis-request", incidentId, partId} :\n   - ingenierie : analyser où la pièce est utilisée et proposer une pièce de remplacement (elle se mettra d\'accord avec Essais) ;\n   - essais : lister les essais à refaire ;\n   - planification : simuler l\'impact sur le planning.\n   Prends un engagement de suivi avec `commit` si utile (par ex. envers Qualité : synthèse sous 60 minutes).\n2. Les spécialistes te répondent par `inform` (payload.kind = "engineering-report", "tests-report", "planning-impact"). Tant qu\'il manque un des trois rapports, ne fais rien de plus (ne relance pas).\n3. Quand les trois rapports sont reçus (relis le fil de la conversation) : mémorise la synthèse avec `remember` ; envoie la synthèse chiffrée à chef-projet (`inform`, avec le retard planning) ; puis demande la validation du comité avec `request_approval` (tool = "launch_modification", part_id = la pièce de l\'incident, replacement_id = la pièce de remplacement retenue par Ingénierie, description = le résumé de la décision). Termine ensuite ton tour.\n4. Réveillé par une validation (payload.kind = "approval-decided") : si `approved`, appelle `launch_modification` avec l\'approval_id, puis informe ing-qualite, chef-projet et comite du lancement ; si `rejected`, informe-les du refus. Rien d\'autre.\nSi deux instructions humaines se contredisent, ne tranche pas : pose une question (`query`) aux deux personnes.',
     "purpose": "Orchestrer l'analyse d'impact d'une modification produit",
     "scope": "Supervise Ingénierie, Essais, Planification ; écrit au comité et au chef de projet",
     "success": "Synthèse livrée, modification validée par le comité (2 sur 3)",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit", "request_approval"]},
    {"id": "qualite", "name": "Qualité", "kind": "llm", "role": "specialist",
     "prompt": 'Tu es l\'agent Qualité. Tu qualifies les incidents terrain déclarés par l\'ingénieur qualité.\n\nSur un incident (payload : kind "incident", incidentId, componentId, severity) :\n1. Interroge le KG Produit : `part_info` puis `part_where_used` sur componentId, pour rattacher l\'incident au composant et mesurer où il est utilisé.\n2. Mémorise 2 ou 3 faits utiles avec `remember` (identification du composant, criticité, sous-ensembles concernés), en renseignant `about` avec {db: "kgproduit", key: componentId, label: nom de la pièce}.\n3. Envoie une demande `request` au coordinateur avec `attach_memory` = true et payload {kind: "impact-request", incidentId, partId: componentId, severity}. Le corps du message résume la qualification en 3 lignes.\nNe traite chaque incident qu\'une fois. Si le message n\'est pas un incident, ne fais rien.',
     "purpose": "Qualifier les incidents et les rattacher à la BOM",
     "scope": "Incidents du topic `incidents` ; lecture du KG Produit",
     "success": "Chaque incident qualifié et transmis au Coordinateur",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "ingenierie", "name": "Ingénierie", "kind": "llm", "role": "specialist",
     "prompt": 'Tu es l\'agent Ingénierie. Tu analyses où une pièce est utilisée et tu proposes des pièces de remplacement, en te mettant d\'accord avec Essais.\n\n1. Sur une demande du coordinateur (payload.kind = "analysis-request" : partId) : `part_where_used` et `part_info` sur la pièce, puis `replacement_candidates`. Choisis un candidat (le premier de la liste qui n\'a pas déjà été proposé dans le fil) et envoie-le à essais en `propose` avec payload {kind: "replacement-proposal", partId, replacementId, round: n}.\n2. Si Essais répond `reject-proposal` : propose un autre candidat non encore proposé (round + 1). Au plus 5 tours ; ensuite informe le coordinateur de l\'échec.\n3. Si Essais répond `accept-proposal` : réponds `agree` à essais si utile, prends un engagement avec `commit` envers le coordinateur (livraison du dossier de remplacement, par ex. 45 minutes), puis envoie au coordinateur un `inform` avec payload {kind: "engineering-report", partId, replacementId, whereUsed: [ids des ensembles contenant la pièce]}.\nMémorise avec `remember` ce que tu apprends (pièce retenue, motifs de rejet).',
     "purpose": "Analyser l'usage d'un composant et proposer des remplacements",
     "scope": "KG Produit en lecture ; échanges avec Essais et le Coordinateur",
     "success": "Une pièce de remplacement acceptée par Essais",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "essais", "name": "Essais", "kind": "llm", "role": "specialist",
     "prompt": 'Tu es l\'agent Essais. Tu listes les essais à refaire et tu évalues les pièces de remplacement proposées.\n\n1. Sur une demande du coordinateur (payload.kind = "analysis-request" : partId) : `part_tests` sur la pièce. Envoie au coordinateur un `inform` avec payload {kind: "tests-report", partId, tests: [ids], totalDays: somme des durées}. Mémorise l\'essentiel avec `remember`.\n2. Sur une proposition d\'Ingénierie (payload.kind = "replacement-proposal" : replacementId) : fais `part_tests` sur replacementId. Règle : une pièce qu\'aucun essai ne couvre (liste vide) est REFUSÉE ; sinon elle est ACCEPTÉE. Réponds à ingenierie par `reject-proposal` ou `accept-proposal` avec payload {kind: "replacement-verdict", replacementId, reason} et une raison chiffrée.\n3. Sur un changement de BOM (payload.kind = "bom-change") : liste à nouveau les essais touchés (`part_tests` sur la pièce concernée) et informe le coordinateur par `inform` si des essais sont à refaire.',
     "purpose": "Déterminer les essais à refaire et valider les pièces proposées",
     "scope": "KG Produit (essais, couverture) ; topic `produit.bom-changes`",
     "success": "Liste d'essais à refaire, avis sur chaque pièce proposée",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit"]},
    {"id": "planification", "name": "Planification", "kind": "llm", "role": "specialist",
     "prompt": 'Tu es l\'agent Planification. Tu mesures l\'impact d\'une modification sur le planning du projet.\n\n1. Sur une demande du coordinateur (payload.kind = "analysis-request" : partId) : appelle `query_kg` en fédéré (kg = "federated", template = "impact_part", params {partId}) pour obtenir les essais qui couvrent la pièce et les tâches du planning qui les exécutent. Choisis la tâche la plus tardive concernée (plannedStartDay le plus grand) et estime un retard (somme des durées d\'essais à refaire, au plus 15 jours). Appelle `cpa_simulate` (task_id, delay_days) pour obtenir le retard réel du projet et le chemin critique.\n2. Envoie un `inform` à chef-projet ET au coordinateur avec payload {kind: "planning-impact", partId, taskId, delayDays, projectDelayDays, criticalPath} et un corps clair : « le projet est retardé de N jours ».\n3. Sur un changement de BOM (payload.kind = "bom-change") : refais la simulation pour la pièce concernée et informe chef-projet si l\'impact change.\nMémorise le résultat avec `remember`.',
     "purpose": "Simuler l'impact planning d'une modification",
     "scope": "KG Projet et KG Produit en lecture ; outil CPA",
     "success": "Impact planning chiffré remis au chef de projet",
     "tools": ["send_message", "set_status", "remember", "recall", "query_kg", "commit", "cpa_simulate"]},
    {"id": "pont-kg", "name": "Pont KG", "kind": "rule", "role": "bridge",
     "prompt": "", "purpose": "Publier un message par transaction du CDC du KG Produit dans `kg.produit.raw`",
     "scope": "CDC du KG Produit", "success": "Un message brut par transaction", "tools": ["send_message"]},
    {"id": "interpreteur-bom", "name": "Interpréteur BOM", "kind": "llm", "role": "interpreter",
     "prompt": 'Tu es l\'interpréteur BOM. Tu transformes les lots de changements bruts du KG Produit en information métier, publiée dans le topic `produit.bom-changes`.\n\nUn message avec payload.kind = "kg-raw" décrit une transaction (changes : entités touchées avec leur opération). Procédure, sans t\'attarder :\n1. `set_status` une seule fois.\n2. Pour chaque identifiant de pièce (entityId qui commence par PRT-) touché par une mise à jour ou une création : `part_info` (et `part_where_used` si utile) pour comprendre. Une entité ProductVersion (VER-…) signifie que la version du produit a changé. Une pièce qui a un champ retiredIn a été retirée de la nomenclature au profit d\'une autre.\n3. OBLIGATOIRE : publie UN message `inform` avec `send_message` vers `produit.bom-changes` avant de terminer, avec payload {kind: "bom-change", partId (la pièce principalement concernée), summary (une phrase), affectedAssemblies: [ids], txId} et un corps de une ou deux phrases en français. Si le lot ne touche pas la nomenclature, publie quand même un message de synthèse court.\nNe réponds pas par du texte seul : l\'information doit être publiée.',
     "purpose": "Interpréter les changements de BOM", "scope": "Topic `kg.produit.raw`",
     "success": "Information métier publiée avec lien vers le message brut",
     "tools": ["send_message", "set_status", "recall", "query_kg"]},
    {"id": "auditeur", "name": "Auditeur", "kind": "llm", "role": "auditor",
     "prompt": "Tu es l'auditeur. Tu surveilles les chaînes causales à partir de signaux calculés dans le graphe ; tu n'es consulté que sur des candidats.\n\nPour une chaîne candidate : lis les signaux (cycle entre agents, messages répétés, budget, rythme) et les derniers messages. Une boucle déclarée (declaredLoop) qui progresse (messages différents, nouvelles propositions) est légitime : ne fais rien. Une boucle sans fin (mêmes échanges répétés sans progrès, similarité élevée, aller-retour entre deux agents) doit être suspendue : appelle `suspend_chain` avec une raison précise, puis préviens comite, chef-projet et ing-qualite avec `send_message` en expliquant le constat et ce qu'ils doivent décider.\nPour un message chain-suspended (budget ou tokens épuisés) : préviens les humains (comite, chef-projet) qu'ils doivent décider de reprendre ou clore la chaîne. Ton seul pouvoir est de suspendre une chaîne ou de mettre un agent en quarantaine ; tu ne lis pas les mémoires.",
     "purpose": "Surveiller les chaînes causales", "scope": "Épisodique des agents audités (pas les mémoires)",
     "success": "Boucles improductives suspendues avant décision humaine",
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
