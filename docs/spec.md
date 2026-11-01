# Spécification PoC — Orchestration d'agents sur Neo4j

Version du 2026-11-01 · Pierre Halftermeyer
Source de vérité : https://claude.ai/artifact/AKWugT8PXQQV2NvAAqLdPi (ce fichier en est un export ; en cas d'écart, le doc fait foi).

## Objet et périmètre

Le PoC démontre une plateforme d'orchestration multi-agents où Neo4j sert à la fois de bus (via le CDC) et de mémoire, sur un scénario d'ingénierie : un incident qui déclenche une modification produit.

- **Cible** : Neo4j Enterprise self-managed (Docker en local), là où l'on maîtrise le CDC et la rétention des logs de transaction.
- **Taille** : 5 agents logiciels, 3 à 4 humains, 1 base d'orchestration, 2 graphes de connaissance.
- **Ce que le PoC doit prouver** : le modèle (inbox, mémoire, droits par chemins, routines, fédération), la gouvernance (budget, auditeur, validations humaines) et la traçabilité (relecture animée à partir du graphe).
- **Hors périmètre** : exigences, fournisseurs, coûts, conformité ; Aura ; contrôle d'accès natif.

À mesurer : la latence entre l'écriture et le réveil, la charge du consommateur CDC, le volume de messages et la consommation de tokens par chaîne.

## Principes du modèle

Le cœur se réduit à quatre notions : des inbox, des messages, des routines et des chemins de droits. Tout le reste en découle.

1. **Tout passe par une inbox.** Messages entre agents, créneaux cron, minuteries, événements, connecteurs et validations humaines déposent tous un message dans une inbox.
2. **Humains et agents logiciels ont le même modèle** (`:Agent:Person` / `:Agent:SoftwareAgent`, alignés sur PROV-O). La politique d'accès, elle, les distingue.
3. **Un agent est défini par son identité et son mandat.** Prompt, modèle et outils forment une `AgentVersion`, versionnée ; une session est un processus éphémère.
4. **On écrit en ajout seul.** Pas de liste chaînée, pas de pointeur à déplacer : des buckets par jour et des `CREATE`.
5. **On révise, on n'écrase pas.** Un fait contredit est fermé (`validTo`) et remplacé (`SUPERSEDES`). Chaque changement d'état garde sa date, ce qui rend la relecture possible.
6. **Un droit d'accès est un chemin dans le graphe** (modèle ReBAC), vérifié par l'application pour l'instant.
7. **Les secrets restent hors du graphe.**
8. **On reprend les standards** quand ils existent : A2A (identité externe, états de tâche), PROV-O (provenance), performatifs FIPA-ACL (intention des messages), OpenTelemetry GenAI (traces).

## Schéma de la base d'orchestration

Chaque agent a trois racines distinctes : son inbox (ce qu'il reçoit), son workspace (ce qu'il a fait) et sa mémoire (ce qu'il sait).

```cypher
// Identité, mandat, définition
(:Agent:Person {id, oidcSub})
(:Agent:SoftwareAgent {id, workloadId})-[:CURRENT]->(:AgentVersion {kind: 'llm'|'rule', prompt, model, toolset})
(:AgentVersion)-[:SUPERSEDES]->(:AgentVersion)
(:Agent)-[:HAS_MANDATE]->(:Mandate {purpose, scope, successCriteria, authoredBy})

// Réception : inbox rangée par jour
(:Agent)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:Day:InboxDay {inboxId, date})
(:InboxDay)-[:RECEIVED {status, submittedAt, workingAt, completedAt}]->(:Message)
(:Inbox:Topic {id, retention})                       // inbox d'événements

// Émission : sessions privées dans le workspace
(:Agent)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:Day:WorkDay {workspaceId, date, summary})
(:WorkDay)-[:OPENED]->(:Session {openedAt, closedAt})-[:SENT]->(:Message)
(:Session)-[:TRIGGERED_BY]->(:Message)
(:Session)-[:RAN_AS]->(:AgentVersion)
(:Session)-[:STATUS]->(:StatusUpdate {text, at})

// Mémoire acquise
(:Agent)-[:HAS_MEMORY]->(:Memory)-[:ASSERTS]->(:Fact {statement, embedding, confidence, validFrom, validTo, memoryId})
(:Fact)-[:ABOUT]->(:EntityRef)
(:Fact)-[:LEARNED_IN]->(:Session)
(:Fact)-[:SUPERSEDES|DERIVED_FROM]->(:Fact)
(:Memory)-[:HAS_PROCEDURE]->(:Procedure)
(:Agent)-[:COMMITTED]->(:Commitment {dueAt, status})

// Message
(:Message {id, from, performative, conversationId, chainId, createdAt, body})
```

**Les cases de la mémoire** (modèle BDI) :

| Case | Contenu | Écrite par |
| --- | --- | --- |
| Mandat | À quoi sert l'agent, son périmètre | Son responsable ; l'agent la lit seulement |
| Interprétation du mandat | Sous-objectifs, compréhension du mandat | L'agent |
| Relations | Superviseurs, destinataires autorisés | Calculé à partir du graphe |
| Engagements | Ce que l'agent a promis, à qui, pour quand | L'agent |
| Connaissances | Les `Fact`, avec leur provenance | L'agent et la consolidation |
| Capacités | Outils et limites | Calculé à partir de `CAN_USE` |

**Contraintes** : clé de nœud sur `InboxDay (inboxId, date)` et `WorkDay (workspaceId, date)` ; unicité sur `Message.id`, `Session.triggerMsgId`, `Agent.id`. Un agent sans mandat ne peut qu'envoyer une question (`query`) à son responsable.

## Droits d'accès

Un agent peut lire une mémoire s'il l'atteint par `SUPERVISES*`, puis par une seule relation terminale. Ce contrôle est fait par l'application pour le PoC.

```cypher
(:Agent)-[:SUPERVISES {since}]->(:Agent)                 // transitif, sans cycle
(:Agent)-[:CAN_SEND_TO]->(:Inbox)
(:Agent)-[:CAN_USE {approval}]->(:Tool)
(:Agent)-[:AUDITS]->(:Agent)                             // lecture de l'épisodique seulement
(:Agent)-[:ACTS_FOR {scope, until}]->(:Agent)            // délégation
(*)-[:CAN_READ {mode: 'snapshot'|'live', asOf, until, private}]->(:Memory)
```

**La grammaire des chemins** (liste blanche, rien d'autre ne transmet un droit) :

```
SUPERVISES*  →  (rien | HAS_INBOX·HAS_DAY·RECEIVED | HAS_WORKSPACE·HAS_DAY·OPENED)  →  HAS_MEMORY | CAN_READ
```

- **Un lien de partage `CAN_READ` peut partir de n'importe quel nœud.** Une mémoire jointe à un message est un `(:Message)-[:CAN_READ]->(:Memory)` : toute personne qui atteint le message lit la mémoire. La purge du message retire le partage.
- **`snapshot` par défaut** : le destinataire voit les faits valides à `asOf`, sans copie. `live` s'accorde explicitement et expire.
- **Un partage remonte la hiérarchie** du destinataire, sauf si `private` est vrai.
- **Pas de partage en cascade** sans droit `CAN_SHARE`. Un fait intégré depuis une mémoire reçue devient un nouveau fait `DERIVED_FROM`.
- **Une seule relation `CAN_READ` par chemin**, toujours en dernier.
- **Créer une relation `SUPERVISES` est une opération privilégiée** (orchestrateur ou administrateur). Le contrôle de cycle se fait à l'écriture, après verrouillage des deux nœuds. La lecture utilise `MATCH ACYCLIC`.
- **Pour un `:Person`** : la supervision ne donne pas d'accès en lecture par défaut, et un agent logiciel ne supervise pas un humain.
- **Le droit d'utiliser un outil ne s'hérite pas** par la supervision.

Requête de périmètre de référence :

```cypher
CYPHER 25
MATCH ACYCLIC (me:Agent {id: $agentId})-[:SUPERVISES]->*(a:Agent)
CALL (me, a) {
  MATCH (a)-[:HAS_MEMORY]->(m:Memory)
  RETURN m, datetime() AS asOf
  UNION
  MATCH (a)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false))
  RETURN m, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf
  UNION
  MATCH (a)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(:Message)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false))
  RETURN m, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf
}
WITH m, max(asOf) AS asOf
RETURN collect({id: m.id, asOf: asOf}) AS scopes
```

**Garanties applicatives** :

- [ ] Les agents n'accèdent jamais directement à la base : passerelle avec des requêtes figées et paramétrées.
- [ ] L'`agentId` vient du contexte d'authentification, jamais du LLM.
- [ ] Un seul chemin de code par type de lecture, avec calcul du périmètre.
- [ ] Tests de non-fuite : mémoire d'un pair, partage `private`, `snapshot` postérieur, partage expiré.
- [ ] Journal des accès dans le graphe.
- [ ] `memoryId` sur chaque `Fact`, et des utilisateurs de base distincts (passerelle, CDC, administration), pour pouvoir passer au contrôle natif plus tard (PBAC et `IMPERSONATE`).

## Graphes de connaissance et fédération

Chaque graphe de connaissance (KG) vit dans sa propre base. Il est relié à la base d'orchestration par des nœuds proxy, jamais par des relations entre bases.

| Niveau | Contenu | Portée | Écriture |
| --- | --- | --- | --- |
| Memory | Croyances d'un agent | Privée, partageable par lien | Libre |
| KG | Savoir partagé et validé | Équipe ou domaine | Extraction, puis validation par un curateur |
| Sources | Documents, systèmes externes | Selon le connecteur | Hors plateforme |

```cypher
// base d'orchestration
(:Fact)-[:ABOUT]->(:Ref:EntityRef {db, key, label})-[:IN_KG]->(:KnowledgeGraph {id, dbName})
// base du KG
(:Entity {id})                                   // id stable, unique, applicatif
(:Assertion {status: 'proposed'|'published'})-[:FROM]->(:Ref:SessionRef {db, key})
```

- **Un seul type de proxy**, `(:Ref {db, key})`, avec un label de rôle, dans les deux sens. Jamais d'`elementId` comme clé.
- **Le proxy copie le moins possible** : la clé et un libellé d'affichage daté.
- **Cycle de vie** : une tâche consomme le CDC du KG pour mettre à jour ou rediriger les proxys (`SAME_AS`) après une fusion ou une suppression d'entité.
- **Pas de fuite par le proxy** : la passerelle vérifie le droit sur le `KnowledgeGraph` avant toute lecture d'un `EntityRef`.
- **Contrôle d'accès natif dans les KG** : un agent peut interroger un KG en lecture seule (requêtes modèles, GraphRAG, éventuellement text2cypher) avec un utilisateur limité à cette base.
- **Requêtes fédérées** par une base composite (`USE graph.byName(...)`).
- **Création** : un extracteur écrit des assertions `proposed` avec leur provenance ; un curateur (agent ou humain) les publie.

**Pour le PoC** : un KG Produit (BOM, composants, versions, essais, couverture), qui appartient au bureau d'études, et un KG Projet (planning, tâches, ressources), qui appartient au PMO.

## Bus : CDC, topics et routines

Un événement est un message dans une inbox de type topic, et une routine est une source de réveil qui dépose un message dans une inbox.

**Le réveil.** Le consommateur CDC interroge `db.cdc.query` en boucle (c'est du polling, pas du push). Il sélectionne les créations de `RECEIVED`, applique les droits, puis réveille l'agent. Il garde un curseur par base et il est idempotent : il déduplique sur `Message.id`, et une session ouverte au réveil est fusionnée (`MERGE`) sur le message qui la déclenche.

**Les routines.**

```cypher
(:Agent)-[:OWNS]->(:Routine {trigger: 'cron'|'once'|'event', cron, tz, runAt, payload, enabled, nextRunAt, misfire})
(:Routine)-[:DELIVERS_TO]->(:Inbox)
(:Routine)-[:LISTENS_TO]->(:Inbox:Topic)          // trigger = 'event'
```

- **cron** : le planificateur calcule `nextRunAt` dans l'application. Un créneau ne se déclenche qu'une fois grâce à la contrainte d'unicité sur `Message.id = routineId@échéance`. Les créneaux manqués sont ignorés par défaut (`misfire = skip`).
- **once** : une minuterie ponctuelle (relance, échéance d'un engagement, escalade).
- **event** : un abonnement à un topic. Le routeur évalue le filtre, un prédicat structuré et jamais du Cypher libre, puis dépose dans l'inbox de l'abonné un message relié à l'événement (`ABOUT_EVENT`).
- `CAN_SEND_TO` est vérifié à la création de la routine **et** à chaque déclenchement.

**Le pipeline d'interprétation du CDC des KG.**

1. **Le pont** est un agent à règles (`AgentVersion.kind = 'rule'`), sans LLM. Il publie un message par transaction dans `kg.<id>.raw`, à rétention courte, avec `kgDb`, `txId` et les identifiants de changement.
2. **Les interpréteurs** sont des agents LLM. Ils transforment ces lots en information métier, publiée dans un topic sémantique (`produit.bom-changes`) avec un lien `DERIVED_FROM` vers le message brut. Le travail est réparti par `entityId` pour garder l'ordre.
3. **Les routeurs** choisissent le destinataire à partir du KG, toujours sous réserve de `CAN_SEND_TO`.

Chaque écriture d'agent renseigne `txMetadata` (auteur, `chainId`), ce qui permet de retrouver la chaîne causale.

**Les connecteurs** sont des agents avec leur propre inbox (e-mail, Slack, notifications aux humains). Un **outil** est un appel synchrone fait dans une session et tracé par un `ToolCall` :

```cypher
(:Session)-[:CALLED]->(:ToolCall {idempotencyKey, status, startedAt, endedAt, tokens})-[:OF]->(:Tool {name, schema, effect: 'read'|'write'|'irreversible', secretRef})
(:ToolCall)-[:PRODUCED]->(:Fact|:Message)
```

## Gouvernance

Les boucles sont autorisées tant qu'elles ont du budget. Trois niveaux les surveillent, du plus rapide au plus intelligent : la passerelle, l'agent auditeur, puis un humain.

```cypher
(:Chain {id, budget, spent, status})<-[:IN_CHAIN]-(:Message)
(:Agent:SoftwareAgent {role: 'auditor'})-[:AUDITS]->(:Agent)
(:Agent {role: 'auditor'})-[:SUSPENDED {reason, at}]->(:Chain)
(:Approval {policy: '2-of-3', status})-[:FOR]->(:ToolCall)
(:Agent:Person)-[:VOTED {decision, at, comment}]->(:Approval)
```

**1. Le budget par chaîne causale.** La passerelle le vérifie à chaque envoi, de façon synchrone. Il se compte en messages, tokens ou euros, et la consommation réelle vient de la réponse du LLM. Une boucle voulue est déclarée (critère d'arrêt, nombre maximal de tours) et reçoit son budget. Un budget épuisé suspend la chaîne et l'envoie à l'auditeur.

**2. L'agent auditeur.** Il part de signaux calculés dans le graphe : cycles récents entre agents (projection GDS sur une fenêtre glissante, composantes fortement connexes), messages répétés (similarité d'embedding), chaîne qui s'élargit ou dépense trop rapide. Il n'utilise le LLM que sur ces candidats. `AUDITS` lui donne accès à l'épisodique, pas aux mémoires. Son seul pouvoir est de suspendre une chaîne ou de mettre un agent en quarantaine. Il ne consomme pas ses propres événements, et ses décisions sont relues par des humains.

**3. Les validations humaines.**

- Une action `irreversible` est validée in fine par des `:Person` uniquement. Un agent logiciel recommande, il ne vote pas.
- Validation à plusieurs signatures : un `Approval` compte les votes, avec une contrainte d'unicité sur le couple (validation, personne).
- Escalade : une routine ponctuelle à 4 h transmet la demande au niveau au-dessus si le quorum n'est pas atteint.
- Absence : une délégation `ACTS_FOR` entre personnes, avec une date de fin.
- Instructions contradictoires : l'agent ne tranche pas. Il envoie une question aux deux personnes, ou à leur responsable commun.
- Statuts alignés sur A2A : `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`.

## Scénario d'ingénierie

Un incident terrain sur un composant déclenche une modification produit. Le scénario passe par chaque mécanisme du modèle.

| Acteur | Type | Rôle |
| --- | --- | --- |
| Coordinateur | Agent LLM | Supervise les trois spécialistes, fait la synthèse |
| Qualité | Agent LLM | Qualifie l'incident, le rattache à la BOM |
| Ingénierie | Agent LLM | Analyse où le composant est utilisé, propose des pièces de remplacement |
| Essais | Agent LLM | Liste les essais à refaire |
| Planification | Agent LLM | Simule l'impact planning (outil Gantt et chemin critique) |
| Pont KG et interpréteur BOM | Agent à règles, puis agent LLM | Transforment le CDC du KG Produit en information |
| Auditeur | Agent | Surveille les chaînes |
| Ingénieur qualité | Humain | Déclare l'incident |
| Comité de modification (2 ou 3 personnes) | Humains | Inbox partagée, validation 2 sur 3 |
| Chef de projet | Humain | Reçoit l'impact planning, peut refuser la date |

1. L'ingénieur qualité publie un incident dans le topic `incidents`.
2. L'agent Qualité, abonné par une routine, rattache l'incident à un composant et enregistre des `Fact`.
3. Il envoie une demande (`request`) au Coordinateur, avec sa mémoire jointe en `snapshot`.
4. Le Coordinateur lance l'analyse d'impact chez Ingénierie, Essais et Planification, avec une requête fédérée KG Produit et KG Projet.
5. **Boucle légitime** : Ingénierie propose une pièce, Essais la rejette, Ingénierie en propose une autre, dans la limite du budget.
6. Les `agree` créent des engagements, suivis par des minuteries.
7. Le Coordinateur demande au comité de valider le lancement de la modification (action irréversible, `input-required`). Les votes arrivent jusqu'au quorum.
8. La version du produit change dans le KG. Le pont et l'interpréteur BOM préviennent les agents Essais et Planification par le topic `produit.bom-changes`.
9. Une routine relance un agent qui n'a pas tenu son engagement à temps.
10. **Chapitre gouvernance** : un aller-retour sans fin entre deux agents, que l'auditeur suspend avant que l'humain décide.

**Données synthétiques** : un produit fictif d'environ 200 pièces sur 3 ou 4 niveaux, une cinquantaine d'essais, une trentaine de tâches de planning, une dizaine d'incidents prévus à l'avance.

## Interface, avatars et relecture

L'interface ne consomme qu'un flux d'événements normalisé. Ce flux est produit en direct, ou reconstruit à partir du graphe pour la relecture : l'interface ne voit pas la différence.

```
{ t, type, actor, target, payload }
type ∈ woken | status | tool.start | tool.end | sent | learned | vote | waiting | idle | error
```

**Les vues.**

- **Chat** : l'inbox de l'humain connecté, qui ne voit que la sienne.
- **Scène** : un plateau 2D avec un poste par agent et par humain, chacun avec sa boîte aux lettres et son étagère « mémoire ».
- **Graphe** (NVL) : topologie, flux de messages, fiche d'un agent, droits (ce qu'un agent peut lire et par quel chemin), KG.
- **Frise** : routines, appels d'outils, votes.
- **Paramètres → Modèles** : la clé du fournisseur LLM.

**Les états des avatars.**

| État | Animation | Source |
| --- | --- | --- |
| Au repos | Respiration lente | Aucune session ouverte |
| Réveillé | Sursaut, l'inbox clignote | Création d'un `RECEIVED` |
| Réfléchit | Bulle avec une phrase courte | `StatusUpdate` (outil `set_status`) |
| Utilise un outil | Icône de l'outil, progression | `ToolCall` en `working` |
| Envoie | Une enveloppe vole vers le destinataire | Création d'un `SENT` |
| Apprend | Une étincelle vers la mémoire | Création d'un `Fact` |
| Attend | Sablier, avatar grisé | Engagement ou `input-required` |
| Erreur | Rouge, secousse | `ToolCall` en `failed` |

**La relecture.** Chaque changement d'état garde sa date. La reconstruction est un `UNION ALL` par type d'événement, trié par `t`. Contrôles : lecture et pause, vitesse de ×1 à ×20, barre de temps, compression des temps morts, chapitres (incident, analyse, vote, lancement, gouvernance), suivi d'un agent.

**Technique** : React, avec SVG et Framer Motion pour commencer ; Rive (state machines) plus tard. Les avatars sont des créations originales.

## Architecture technique

Une seule passerelle sert l'interface, les agents et les connecteurs. Le même flux CDC réveille les agents et anime l'interface.

```
 Interface      Connecteurs     Fournisseur LLM     Runtimes d'agents
 (React, NVL)   (e-mail, Slack) (Gemini, abstrait)  (LLM et règles)
      │              │                ▲                    │      ▲
      ▼              ▼                │                    ▼      │ réveil
 ┌───────────────────────── Passerelle ──────────────────────────┐ │
 │ requêtes figées, droits ReBAC, budget, abstraction LLM, clé   │ │
 └───────────────────────────────┬───────────────────────────────┘ │
                                 │ Cypher                          │
 ┌──── Neo4j Enterprise (Docker) ┴─────────────┐   CDC   ┌─────────┴────────┐
 │ orchestration │ KG Produit │ KG Projet │ fed │ ──────► │ Consommateur CDC │
 └──────────────────────────────────────────────┘         │ routeur, pont KG │
                                                          │ planificateur    │
      ▲ WebSocket : flux d'événements ────────────────────└──────────────────┘
```

- **Neo4j Enterprise en local (Docker)** : une base d'orchestration, une base par KG et une base composite pour la fédération. Utilisateurs distincts pour la passerelle, le CDC et l'administration.
- **Passerelle** : requêtes figées, calcul des droits, contrôle du budget, journal des accès, appels au LLM pour le compte des runtimes.
- **Consommateur CDC** : un curseur par base, le routage des topics, le pont des KG, le planificateur des routines, et le flux d'événements vers l'interface.
- **Runtimes d'agents** : agents LLM et agents à règles ; ils n'ont ni clé LLM ni accès direct à la base.

**Abstraction du fournisseur LLM.** La passerelle expose une interface unique (génération, appel d'outils, embeddings, comptage des tokens). Gemini est le premier fournisseur branché ; un autre s'ajoute sans toucher aux agents. `AgentVersion.model` indique le modèle de chaque agent, et changer de modèle crée une nouvelle version.

**Clé Gemini** (Paramètres → Modèles, réservé à un administrateur) : champ en écriture seule (seuls les 4 derniers caractères et la date sont réaffichés) ; bouton Tester (appelle la liste des modèles, valide la clé et remplit la liste déroulante) ; boutons Remplacer et Supprimer ; stockage chiffré par la passerelle (clé maître en variable d'environnement), hors du graphe, du dépôt, des journaux et du navigateur.

## Points à vérifier et questions ouvertes

**À vérifier sur la version cible de Neo4j :**

- [ ] `MATCH ACYCLIC` et `MATCH ANY` sur les motifs quantifiés.
- [ ] `USE graph.byName(...)` avec un nom calculé, dans un `CALL` sur une base composite.
- [ ] Les privilèges exacts exigés par `db.cdc.query`.
- [ ] Le filtrage dans l'index vectoriel (clause `SEARCH`), par rapport à un filtre appliqué après la recherche.
- [ ] Plus tard : PBAC avec `IN`, et l'effet du PBAC sur le top-k vectoriel.

**Questions ouvertes :**

- [ ] La supervision donne-t-elle accès à l'épisodique du subordonné (`Workspace`, sessions) ?
- [ ] Qui écrit le mandat : toujours un humain, ou un agent dans la limite de son propre mandat ?
- [ ] Le découpage des KG : par domaine ou par équipe ?
- [ ] Le text2cypher dans les KG est-il autorisé dès le PoC ?
- [ ] Le curateur : agent, humain, ou agent avec validation humaine selon le type d'assertion ?
- [ ] La granularité des buckets : jour ou heure.
