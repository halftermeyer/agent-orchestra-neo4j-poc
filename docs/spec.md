# PoC specification — Agent orchestration on Neo4j

Version of 2026-11-01 · Pierre Halftermeyer
Source of truth: https://claude.ai/artifact/AKWugT8PXQQV2NvAAqLdPi (this file is an export of it, translated to English on 2026-11-02; in case of discrepancy, the original document prevails).

## Purpose and scope

The PoC demonstrates a multi-agent orchestration platform where Neo4j serves both as the bus (via CDC) and as the memory, on an engineering scenario: an incident that triggers a product change.

- **Target**: self-managed Neo4j Enterprise (Docker, local), where CDC and transaction log retention can be controlled.
- **Size**: 5 software agents, 3 to 4 people, 1 orchestration database, 2 knowledge graphs.
- **What the PoC must prove**: the model (inbox, memory, path-based rights, routines, federation), governance (budget, auditor, human approvals) and traceability (animated replay built from the graph).
- **Out of scope**: requirements, vendors, costs, compliance; Aura; native access control.

To be measured: the latency between write and wake-up, the load on the CDC consumer, the message volume and the token consumption per chain.

## Model principles

The core boils down to four notions: inboxes, messages, routines and rights paths. Everything else follows from them.

1. **Everything goes through an inbox.** Messages between agents, cron slots, timers, events, connectors and human approvals all drop a message into an inbox.
2. **People and software agents share the same model** (`:Agent:Person` / `:Agent:SoftwareAgent`, aligned with PROV-O). The access policy, however, tells them apart.
3. **An agent is defined by its identity and its mandate.** Prompt, model and tools form a versioned `AgentVersion`; a session is an ephemeral process.
4. **We write append-only.** No linked list, no pointer to move: daily buckets and `CREATE`.
5. **We revise, we never overwrite.** A contradicted fact is closed (`validTo`) and replaced (`SUPERSEDES`). Every state change keeps its date, which makes replay possible.
6. **An access right is a path in the graph** (ReBAC model), enforced by the application for now.
7. **Secrets stay out of the graph.**
8. **We reuse standards** when they exist: A2A (external identity, task states), PROV-O (provenance), FIPA-ACL performatives (message intent), OpenTelemetry GenAI (traces).

## Orchestration database schema

Each agent has three distinct roots: its inbox (what it receives), its workspace (what it has done) and its memory (what it knows).

```cypher
// Identity, mandate, definition
(:Agent:Person {id, oidcSub})
(:Agent:SoftwareAgent {id, workloadId})-[:CURRENT]->(:AgentVersion {kind: 'llm'|'rule', prompt, model, toolset})
(:AgentVersion)-[:SUPERSEDES]->(:AgentVersion)
(:Agent)-[:HAS_MANDATE]->(:Mandate {purpose, scope, successCriteria, authoredBy})

// Reception: inbox organised by day
(:Agent)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:Day:InboxDay {inboxId, date})
(:InboxDay)-[:RECEIVED {status, submittedAt, workingAt, completedAt}]->(:Message)
(:Inbox:Topic {id, retention})                       // event inbox

// Sending: private sessions in the workspace
(:Agent)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:Day:WorkDay {workspaceId, date, summary})
(:WorkDay)-[:OPENED]->(:Session {openedAt, closedAt})-[:SENT]->(:Message)
(:Session)-[:TRIGGERED_BY]->(:Message)
(:Session)-[:RAN_AS]->(:AgentVersion)
(:Session)-[:STATUS]->(:StatusUpdate {text, at})

// Acquired memory
(:Agent)-[:HAS_MEMORY]->(:Memory)-[:ASSERTS]->(:Fact {statement, embedding, confidence, validFrom, validTo, memoryId})
(:Fact)-[:ABOUT]->(:EntityRef)
(:Fact)-[:LEARNED_IN]->(:Session)
(:Fact)-[:SUPERSEDES|DERIVED_FROM]->(:Fact)
(:Memory)-[:HAS_PROCEDURE]->(:Procedure)
(:Agent)-[:COMMITTED]->(:Commitment {dueAt, status})

// Message
(:Message {id, from, performative, conversationId, chainId, createdAt, body})
```

**The memory "cases"** (BDI model):

| Case | Content | Written by |
| --- | --- | --- |
| Mandate | What the agent is for, its scope | Its manager; the agent only reads it |
| Mandate interpretation | Sub-goals, understanding of the mandate | The agent |
| Relations | Supervisors, authorised recipients | Computed from the graph |
| Commitments | What the agent promised, to whom, by when | The agent |
| Knowledge | The `Fact` nodes, with their provenance | The agent and consolidation |
| Capabilities | Tools and limits | Computed from `CAN_USE` |

**Constraints**: node key on `InboxDay (inboxId, date)` and `WorkDay (workspaceId, date)`; uniqueness on `Message.id`, `Session.triggerMsgId`, `Agent.id`. An agent without a mandate can only send a question (`query`) to its manager.

## Access rights

An agent can read a memory if it reaches it through `SUPERVISES*`, then through a single terminal relationship. For the PoC, this check is performed by the application.

```cypher
(:Agent)-[:SUPERVISES {since}]->(:Agent)                 // transitive, acyclic
(:Agent)-[:CAN_SEND_TO]->(:Inbox)
(:Agent)-[:CAN_USE {approval}]->(:Tool)
(:Agent)-[:AUDITS]->(:Agent)                             // episodic read only
(:Agent)-[:ACTS_FOR {scope, until}]->(:Agent)            // delegation
(*)-[:CAN_READ {mode: 'snapshot'|'live', asOf, until, private}]->(:Memory)
```

**The path grammar** (allow list; nothing else conveys a right):

```
SUPERVISES*  →  (nothing | HAS_INBOX·HAS_DAY·RECEIVED | HAS_WORKSPACE·HAS_DAY·OPENED)  →  HAS_MEMORY | CAN_READ
```

- **A `CAN_READ` sharing link can start from any node.** A memory attached to a message is a `(:Message)-[:CAN_READ]->(:Memory)`: anyone who reaches the message reads the memory. Purging the message removes the share.
- **`snapshot` by default**: the recipient sees the facts valid at `asOf`, without a copy. `live` is granted explicitly and expires.
- **A share goes up the hierarchy** of the recipient, unless `private` is true.
- **No cascading shares** without a `CAN_SHARE` right. A fact integrated from a received memory becomes a new `DERIVED_FROM` fact.
- **A single `CAN_READ` relationship per path**, always last.
- **Creating a `SUPERVISES` relationship is a privileged operation** (orchestrator or administrator). The cycle check is done at write time, after locking both nodes. Reads use `MATCH ACYCLIC`.
- **For a `:Person`**: supervision gives no read access by default, and a software agent does not supervise a human.
- **The right to use a tool is not inherited** through supervision.

Reference scope query:

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

**Application guarantees**:

- [ ] Agents never access the database directly: gateway with frozen, parameterised queries.
- [ ] The `agentId` comes from the authentication context, never from the LLM.
- [ ] A single code path per type of read, with scope computation.
- [ ] No-leak tests: a peer's memory, a `private` share, a later `snapshot`, an expired share.
- [ ] Access log in the graph.
- [ ] `memoryId` on every `Fact`, and distinct database users (gateway, CDC, administration), so that we can move to native access control later (PBAC and `IMPERSONATE`).

## Knowledge graphs and federation

Each knowledge graph (KG) lives in its own database. It is linked to the orchestration database through proxy nodes, never through relationships between databases.

| Level | Content | Reach | Write |
| --- | --- | --- | --- |
| Memory | An agent's beliefs | Private, shareable by link | Free |
| KG | Shared, validated knowledge | Team or domain | Extraction, then approval by a curator |
| Sources | Documents, external systems | Depends on the connector | Outside the platform |

```cypher
// orchestration database
(:Fact)-[:ABOUT]->(:Ref:EntityRef {db, key, label})-[:IN_KG]->(:KnowledgeGraph {id, dbName})
// KG database
(:Entity {id})                                   // stable, unique, application-level id
(:Assertion {status: 'proposed'|'published'})-[:FROM]->(:Ref:SessionRef {db, key})
```

- **A single proxy type**, `(:Ref {db, key})`, with a role label, in both directions. Never an `elementId` as a key.
- **The proxy copies as little as possible**: the key and a dated display label.
- **Lifecycle**: a task consumes the KG's CDC to update or redirect the proxies (`SAME_AS`) after an entity merge or deletion.
- **No leak through the proxy**: the gateway checks the right on the `KnowledgeGraph` before any read of an `EntityRef`.
- **Native access control in the KGs**: an agent can query a KG read-only (template queries, GraphRAG, possibly text2cypher) with a user restricted to that database.
- **Federated queries** through a composite database (`USE graph.byName(...)`).
- **Creation**: an extractor writes `proposed` assertions with their provenance; a curator (agent or human) publishes them.

**For the PoC**: a Product KG (BOM, components, versions, tests, coverage), owned by the engineering department, and a Project KG (planning, tasks, resources), owned by the PMO.

## Bus: CDC, topics and routines

An event is a message in a topic-type inbox, and a routine is a wake-up source that drops a message into an inbox.

**The wake-up.** The CDC consumer polls `db.cdc.query` in a loop (this is polling, not push). It selects the creations of `RECEIVED`, applies the rights, then wakes the agent. It keeps one cursor per database and is idempotent: it deduplicates on `Message.id`, and a session opened at wake-up is merged (`MERGE`) on the message that triggers it.

**Routines.**

```cypher
(:Agent)-[:OWNS]->(:Routine {trigger: 'cron'|'once'|'event', cron, tz, runAt, payload, enabled, nextRunAt, misfire})
(:Routine)-[:DELIVERS_TO]->(:Inbox)
(:Routine)-[:LISTENS_TO]->(:Inbox:Topic)          // trigger = 'event'
```

- **cron**: the scheduler computes `nextRunAt` in the application. A slot fires only once thanks to the uniqueness constraint on `Message.id = routineId@deadline`. Missed slots are ignored by default (`misfire = skip`).
- **once**: a one-off timer (reminder, commitment deadline, escalation).
- **event**: a subscription to a topic. The router evaluates the filter, a structured predicate and never free-form Cypher, then drops into the subscriber's inbox a message linked to the event (`ABOUT_EVENT`).
- `CAN_SEND_TO` is checked when the routine is created **and** at every trigger.

**The KG CDC interpretation pipeline.**

1. **The bridge** is a rule-based agent (`AgentVersion.kind = 'rule'`), with no LLM. It publishes one message per transaction in `kg.<id>.raw`, with short retention, carrying `kgDb`, `txId` and the change identifiers.
2. **The interpreters** are LLM agents. They turn these batches into business information, published in a semantic topic (`produit.bom-changes`) with a `DERIVED_FROM` link to the raw message. Work is partitioned by `entityId` to preserve ordering.
3. **The routers** choose the recipient from the KG, always subject to `CAN_SEND_TO`.

Every agent write fills in `txMetadata` (author, `chainId`), which makes it possible to retrieve the causal chain.

**Connectors** are agents with their own inbox (e-mail, Slack, notifications to people). A **tool** is a synchronous call made within a session and traced by a `ToolCall`:

```cypher
(:Session)-[:CALLED]->(:ToolCall {idempotencyKey, status, startedAt, endedAt, tokens})-[:OF]->(:Tool {name, schema, effect: 'read'|'write'|'irreversible', secretRef})
(:ToolCall)-[:PRODUCED]->(:Fact|:Message)
```

## Governance

Loops are allowed as long as they have budget. Three levels watch over them, from the fastest to the smartest: the gateway, the auditor agent, then a human.

```cypher
(:Chain {id, budget, spent, status})<-[:IN_CHAIN]-(:Message)
(:Agent:SoftwareAgent {role: 'auditor'})-[:AUDITS]->(:Agent)
(:Agent {role: 'auditor'})-[:SUSPENDED {reason, at}]->(:Chain)
(:Approval {policy: '2-of-3', status})-[:FOR]->(:ToolCall)
(:Agent:Person)-[:VOTED {decision, at, comment}]->(:Approval)
```

**1. The budget per causal chain.** The gateway checks it on every send, synchronously. It is counted in messages, tokens or euros, and actual consumption comes from the LLM response. An intentional loop is declared (stop criterion, maximum number of turns) and receives its own budget. An exhausted budget suspends the chain and sends it to the auditor.

**2. The auditor agent.** It starts from signals computed in the graph: recent cycles between agents (GDS projection over a sliding window, strongly connected components), repeated messages (embedding similarity), a chain that widens or spends too fast. It uses the LLM only on these candidates. `AUDITS` gives it access to the episodic memory, not to the memories. Its only power is to suspend a chain or put an agent in quarantine. It does not consume its own events, and its decisions are reviewed by humans.

**3. Human approvals.**

- An `irreversible` action is ultimately approved by `:Person` nodes only. A software agent recommends; it does not vote.
- Multi-signature approval: an `Approval` counts the votes, with a uniqueness constraint on the (approval, person) pair.
- Escalation: a one-off routine at 4 h forwards the request to the level above if the quorum is not reached.
- Absence: an `ACTS_FOR` delegation between people, with an end date.
- Contradictory instructions: the agent does not decide. It sends a question to both people, or to their common manager.
- Statuses aligned with A2A: `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled`.

## Engineering scenario

A field incident on a component triggers a product change. The scenario goes through every mechanism of the model.

| Actor | Type | Role |
| --- | --- | --- |
| Coordinator | LLM agent | Supervises the three specialists, does the synthesis |
| Quality | LLM agent | Qualifies the incident, links it to the BOM |
| Engineering | LLM agent | Analyses where the component is used, proposes replacement parts |
| Tests | LLM agent | Lists the tests to redo |
| Planning | LLM agent | Simulates the planning impact (Gantt tool and critical path) |
| KG bridge and BOM interpreter | Rule-based agent, then LLM agent | Turn the Product KG's CDC into information |
| Auditor | Agent | Watches the chains |
| Quality engineer | Human | Reports the incident |
| Change committee (2 or 3 people) | Humans | Shared inbox, 2-of-3 approval |
| Project manager | Human | Receives the planning impact, can reject the date |

1. The quality engineer publishes an incident in the `incidents` topic.
2. The Quality agent, subscribed through a routine, links the incident to a component and records `Fact` nodes.
3. It sends a request (`request`) to the Coordinator, with its memory attached as a `snapshot`.
4. The Coordinator launches the impact analysis with Engineering, Tests and Planning, using a federated query across the Product KG and the Project KG.
5. **Legitimate loop**: Engineering proposes a part, Tests rejects it, Engineering proposes another, within the budget limit.
6. The `agree` messages create commitments, tracked by timers.
7. The Coordinator asks the committee to approve the launch of the change (irreversible action, `input-required`). Votes come in until the quorum is reached.
8. The product version changes in the KG. The bridge and the BOM interpreter notify the Tests and Planning agents through the `produit.bom-changes` topic.
9. A routine nudges an agent that did not honour its commitment in time.
10. **Governance chapter**: an endless back-and-forth between two agents, which the auditor suspends before the human decides.

**Synthetic data**: a fictional product of about 200 parts over 3 or 4 levels, about fifty tests, about thirty planning tasks, about ten incidents prepared in advance.

## Interface, avatars and replay

The interface consumes only a normalised event stream. This stream is produced live, or rebuilt from the graph for replay: the interface cannot tell the difference.

```
{ t, type, actor, target, payload }
type ∈ woken | status | tool.start | tool.end | sent | learned | vote | waiting | idle | error
```

**The views.**

- **Chat**: the inbox of the logged-in human, who sees only their own.
- **Scene**: a 2D board with one desk per agent and per human, each with its mailbox and its "memory" shelf.
- **Graph** (NVL): topology, message flow, an agent's card, rights (what an agent can read and through which path), KG.
- **Timeline**: routines, tool calls, votes.
- **Settings → Models**: the LLM provider key.

**Avatar states.**

| State | Animation | Source |
| --- | --- | --- |
| Idle | Slow breathing | No open session |
| Woken | Startle, the inbox blinks | Creation of a `RECEIVED` |
| Thinking | Bubble with a short sentence | `StatusUpdate` (`set_status` tool) |
| Using a tool | Tool icon, progress | `ToolCall` in `working` |
| Sending | An envelope flies to the recipient | Creation of a `SENT` |
| Learning | A spark towards the memory | Creation of a `Fact` |
| Waiting | Hourglass, greyed-out avatar | Commitment or `input-required` |
| Error | Red, shaking | `ToolCall` in `failed` |

**Replay.** Every state change keeps its date. The reconstruction is a `UNION ALL` per event type, sorted by `t`. Controls: play and pause, speed from ×1 to ×20, time bar, compression of dead time, chapters (incident, analysis, vote, launch, governance), following an agent.

**Technology**: React, with SVG and Framer Motion to start with; Rive (state machines) later. The avatars are original creations.

## Technical architecture

A single gateway serves the interface, the agents and the connectors. The same CDC stream wakes the agents and animates the interface.

```
 Interface      Connectors      LLM provider        Agent runtimes
 (React, NVL)   (e-mail, Slack) (Gemini, abstract)  (LLM and rules)
      │              │                ▲                    │      ▲
      ▼              ▼                │                    ▼      │ wake-up
 ┌───────────────────────── Gateway ─────────────────────────────┐ │
 │ frozen queries, ReBAC rights, budget, LLM abstraction, key    │ │
 └───────────────────────────────┬───────────────────────────────┘ │
                                 │ Cypher                          │
 ┌──── Neo4j Enterprise (Docker) ┴─────────────┐   CDC   ┌─────────┴────────┐
 │ orchestration │ KG Produit │ KG Projet │ fed │ ──────► │ CDC consumer     │
 └──────────────────────────────────────────────┘         │ router, KG bridge│
                                                          │ scheduler        │
      ▲ WebSocket: event stream ──────────────────────────└──────────────────┘
```

- **Local Neo4j Enterprise (Docker)**: one orchestration database, one database per KG and one composite database for federation. Distinct users for the gateway, the CDC and administration.
- **Gateway**: frozen queries, rights computation, budget control, access log, calls to the LLM on behalf of the runtimes.
- **CDC consumer**: one cursor per database, topic routing, the KG bridge, the routine scheduler, and the event stream to the interface.
- **Agent runtimes**: LLM agents and rule-based agents; they have neither an LLM key nor direct access to the database.

**LLM provider abstraction.** The gateway exposes a single interface (generation, tool calling, embeddings, token counting). Gemini is the first provider plugged in; another can be added without touching the agents. `AgentVersion.model` indicates each agent's model, and changing the model creates a new version.

**Gemini key** (Settings → Models, restricted to an administrator): write-only field (only the last 4 characters and the date are displayed again); Test button (calls the model list, validates the key and fills the dropdown); Replace and Delete buttons; encrypted storage by the gateway (master key in an environment variable), outside the graph, the repository, the logs and the browser.

## Points to verify and open questions

**To verify on the target Neo4j version:**

- [ ] `MATCH ACYCLIC` and `MATCH ANY` on quantified patterns.
- [ ] `USE graph.byName(...)` with a computed name, inside a `CALL` on a composite database.
- [ ] The exact privileges required by `db.cdc.query`.
- [ ] Filtering inside the vector index (`SEARCH` clause), compared with a filter applied after the search.
- [ ] Later: PBAC with `IN`, and the effect of PBAC on the vector top-k.

**Open questions:**

- [ ] Does supervision give access to the subordinate's episodic memory (`Workspace`, sessions)?
- [ ] Who writes the mandate: always a human, or an agent within the limits of its own mandate?
- [ ] How to split the KGs: by domain or by team?
- [ ] Is text2cypher in the KGs allowed from the PoC onwards?
- [ ] The curator: agent, human, or agent with human approval depending on the assertion type?
- [ ] Bucket granularity: day or hour.
