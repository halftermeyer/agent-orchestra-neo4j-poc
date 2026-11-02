# Spikes — Phase 0

Version tested: **Neo4j 2026.09.0 Enterprise** (image `neo4j:2026.09.0-enterprise`), Cypher 5 and 25 available, APOC (core) and GDS installed via `NEO4J_PLUGINS`. Python driver `neo4j` 6.4.1. Scripts: `agent-orchestra-poc/spikes/`.

Summary: all the spec's hypotheses are confirmed, with four caveats (★) to carry into the following phases.

## 1. `MATCH ACYCLIC` and `MATCH ANY` on `-[:SUPERVISES]->*` ✅

Graph: `a→b→c→a` (cycle) and `b→d`. Start at `a`.

| Query | Result |
| --- | --- |
| `MATCH ACYCLIC (me {id:'a'})-[:SUPERVISES]->*(x)` | `a, b, c, d` (each once; `a` = path of length 0) |
| `MATCH ANY (me {id:'a'})-[:SUPERVISES]->*(x)` | `a, b, c, d` (one path per endpoint) |
| `MATCH (me {id:'a'})-[:SUPERVISES]->*(x)` (no keyword) | `a, a, b, c, …`: duplicates, the cycle is traversed once |

★ The `->*` pattern includes the path of length 0: `me` is part of its own scope, which the spec's scope query already assumes (`a = me`). The `ACYCLIC` keyword must therefore be kept in all supervision queries. `path` is not bound implicitly (`MATCH ANY SHORTEST … length(path)` fails): you have to write `p = …`.

## 2. CDC ✅

- `ALTER DATABASE <db> SET OPTION txLogEnrichment 'FULL'` works (visible in `SHOW DATABASES … options`). The database restarts; `db.cdc.current()` then responds.
- `db.cdc.query(cursor, selectors)`: events carry `txId`, `seq`, `metadata`, `event.eventType` (`n`/`r`), `event.operation` (`c`/`u`/`d`) and `event.state.after.properties`. The selector `[{select:'n', labels:['Message']}]` filters correctly.
- ★ **Minimal privileges of a CDC user**: `ACCESS` on the database **and** `EXECUTE BOOSTED PROCEDURE db.cdc.*` ON DBMS. A plain `EXECUTE PROCEDURE` is denied; `MATCH {*}` is not required. Without `ACCESS` on the database, it is denied.
- ★ Security consequence: the `cdc` user reads **all** properties of all events without the `MATCH` privilege. The CDC account must stay internal (never exposed to the UI); rights-based filtering happens in the router.
- Transaction log retention set to `2 days` in the compose file (`db.tx_log.rotation.retention_policy`) so that the cursor survives a CDC consumer shutdown.

## 3. Composite database `fed` ✅

`CREATE COMPOSITE DATABASE fed` + aliases `fed.orchestra`, `fed.kgproduit`, `fed.kgprojet`. These work:

- `USE fed.kgproduit MATCH …`;
- `UNWIND ['kgproduit','kgprojet'] AS g CALL (g) { USE graph.byName('fed.' + g) MATCH … RETURN … } RETURN …`: computed name inside a `CALL` with explicit scope, with results from both KGs.

To remember: `graph.byName` expects the **qualified** name (`fed.kgproduit`). Graph names must come from an allow-list on the gateway side (never from LLM input).

## 4. Vector index with filter ✅ (`SEARCH` clause available)

- `db.index.vector.queryNodes` is **deprecated** (replaced by `SEARCH`); a post-filter on the top 10 returns only 5 results out of the 10 requested (50% loss).
- ★ `SEARCH f IN (VECTOR INDEX … FOR $v WHERE f.memoryId = 'm1' LIMIT 10)` only works if the filter property is declared at creation: `CREATE VECTOR INDEX … FOR (f:Fact) ON (f.embedding) WITH [f.memoryId] OPTIONS {…}`. Otherwise: `22ND3 … not an additional property`. With the declaration: 10 results, all with the right `memoryId`, and `IN [...]` works too.
- Decision proposed for phase 1: `fact_embedding` index with `WITH [f.memoryId]`. The ReBAC scope filter is done through `memoryId IN $scopeIds`; the `asOf` filter (`validFrom`/`validTo`) remains a post-filter. I therefore request a large `LIMIT` (k×3) before the `asOf` post-filter. The embedding dimensions depend on the Gemini model: to be fixed in phase 2.

## 5. `apoc.util.validate` in a write ✅

`CREATE (x) WITH x CALL apoc.util.validate(true, 'budget exceeded %d', [5])` raises an error (`ProcedureCallFailed`) and the transaction is rolled back: the node is not persisted. With `false`, the query goes through. Usable for the chain budget and write guards, with the gateway having to map the error to an HTTP 4xx.

## 6. Write → CDC event latency ✅

Decoupled writer and poller (writes at a random interval of 50–400 ms, 30 messages per trial, local Docker, single instance):

| Polling | p50 | mean | p95 | max |
| --- | --- | --- | --- | --- |
| 100 ms | 71 ms | 64 ms | 116 ms | 120 ms |
| 250 ms | 123 ms | 111 ms | 236 ms | 254 ms |
| 500 ms | 256 ms | 249 ms | 466 ms | 516 ms |

Latency tracks ≈ interval/2: CDC itself adds almost nothing (< 15 ms measured when reading immediately after commit). **Proposed choice: 100 ms** (negligible load locally). A first measurement with a synchronous writer was invalid (the first poll always found the event) and was discarded.

## Deviations from the spec

None blocking. Points of attention: (★) above; `SEARCH` makes the post-filter unnecessary for rights but not for `asOf`.

## Phase 1 notes

- **Deviation / addition to approve**: the spec requires checking "the right on the `KnowledgeGraph`" without naming the relationship. The seed introduces `(:Agent)-[:CAN_QUERY {mode:'read'}]->(:KnowledgeGraph)`. This will be an explicit branch of the scope query (rule 6).
- Without the `MATCH` privilege, a user reads **zero rows** (no error): the `cdc` account sees no node live, but `db.cdc.query` returns everything to it.
- The `PUBLIC` role has `EXECUTE PROCEDURE *` by default; the `GRANT EXECUTE PROCEDURE apoc.util.*/gds.*` for `gateway_rw` is therefore redundant but explicit.
- The gateway needs `NAME MANAGEMENT` on `orchestra` (dynamic creation of labels/relationship types at runtime).
- `VOTED` carries `approvalId` and `personId` to support the relationship uniqueness constraint (the pair cannot be expressed otherwise).

## Phase 2 notes (gateway)

- **Session key**: `Session.triggerMsgId = <messageId>@<agentId>` (and `direct:<messageId>@<personId>` for a human message). The same message sent to two inboxes would wake two agents with the same `messageId`; the spec's global uniqueness therefore required a composite key. The `TRIGGERED_BY` link always points to the `Message`.
- **Scope query**: the reference query is taken as is, with a restriction for supervised `:Person` nodes (the own-memory and inbox branches require `a = me OR NOT a:Person`). The `HAS_WORKSPACE·HAS_DAY·OPENED` branch of the grammar is not implemented: no `CAN_READ` relationship leaves a `Session` in the PoC (rule 6: no branch without a need).
- **Chain**: in addition to `budget`/`spent` (messages), `tokenBudget`/`tokensSpent`. An exhausted budget moves the chain to `suspended` (with `suspendedAt`, `suspendReason`) in the transaction that detects the overrun; resuming is a human action (`resumedAt`). Declared loops (`stopCriterion`, `maxTurns`) are only created by the administrator for now.
- **Access log**: nodes `(:AccessLog {agentId, kind, granted, targets, at})` linked to the agent by the `agentId` property, not by a relationship (avoids a supernode); to be re-bucketed by day if volume justifies it.
- **`CAN_SHARE`**: relationship `(:Agent)-[:CAN_SHARE]->(:Memory)` added for re-sharing ("no cascade without CAN_SHARE").
- **Cypher 25 syntax encountered**: `ORDER BY` after `RETURN` only accepts aliases; the path variable goes before the selector (`MATCH path = ANY (a)<-[:R]-+(b)`).
- **Real Gemini** (environment key): list of 46 models including `gemini-2.5-flash`; `gemini-embedding-001` embeddings at 768 dimensions; tool calling and token counting validated.
- **Gateway port**: 18000 (`make gateway`). Tokens: `python -m orchestra.gateway.tokens svc|user|admin <id>` (HMAC of the master key, no storage). `make keygen` adds `ORCHESTRA_MASTER_KEY` to `.env` without displaying it.
- **Remaining for later phases**: commitments (`commit`), the router's `ABOUT_EVENT`, `AUDITS` as episodic read for the auditor, demo login for the UI users.

## Phase 3 notes (CDC consumer)

- **CDC `keys` = node keys only.** A simple uniqueness constraint does not populate `keys` (observed on `Message`). To identify entities from events alone (the `cdc` account can read nothing else), these constraints are switched to `NODE KEY`: `Agent.id`, `Message.id`, `Session.triggerMsgId`, `Inbox.id`, `Memory.id`, `Chain.id`, `Tool.name`, `ToolCall.idempotencyKey`, `Approval.id`, `Entity.id` (KG). Stricter than the spec's uniqueness, hence compatible. The old constraints are dropped by the init script (`DROP … IF EXISTS`); names: `*_key`.
- **Cursor in a file, not in the graph.** Writing the cursor into the watched database produces a CDC event, hence a new cursor: infinite loop. One JSON file per installation (volume `cdc-data`), atomic write, one cursor per database. First start: current position (`db.cdc.current`), the seed is not replayed. Not handled: a cursor older than the log retention (2 days in the compose file).
- **Consumer writes = gateway.** The consumer reads CDC with the `cdc` user and writes only through `/internal/*` (`sys` token, derived from the master key): message delivery (`/internal/deliver`), routine progress, `EntityRef` synchronization. The `txMetadata` carry the acting agent and the chain.
- **System messages** (routines, topics, bridge): `Message.from` = `routine:<id>` or `pont-kg`, `actingAgent` = the agent whose `CAN_SEND_TO` and budget apply, no `Session`/`SENT` (no agent writes). Deterministic ids (`evt:<routine>:<msg>`, `raw:<db>:<tx>`, `<routine>@<slot>`): the node key on `Message.id` provides idempotence. Delivery into its own inbox is allowed without `CAN_SEND_TO` (the seed's routines declare none).
- **Chains**: an event routine inherits the chain of the triggering message; a cron slot opens its own chain; a KG transaction opens its own, unless its `txMetadata` carries a `chainId` (the causal chain of the change is then reused).
- **KG bridge**: implemented by the consumer acting as `pont-kg` (rule-based agent); no dedicated runtime needed. One message per transaction, `kgDb`, `txId`, at most 200 changes (`truncated`), entity identifiers taken from the node keys.
- **Routines**: `nextRunAt` computed application-side (croniter, routine timezone); `misfire = skip` ignores a slot more than 60 s late; a `once` timer defaults to `misfire = fire` (a follow-up must not disappear after a shutdown). `CAN_SEND_TO` is checked at creation (`POST /routines`) and on each trigger (failure recorded in `lastError`).
- **Wake-up**: `/ws/wake` (service token, a runtime receives only its own wake-ups); catch-up via `GET /inbox/pending`. No wake-up for a quarantined agent or for a suspended chain. **Stream**: `/ws/events` (recent history replayed on connection), `GET /stats` (CDC lag → processing).
- **Measurements** (local Docker, 100 ms polling): send → runtime wake-up p50 82 ms, p95 86 ms (15 trials); commit → processing lag p50 ≈ 110 ms in real conditions.
- **Known limitations**: a single sequential loop for the three databases; no partitioning by `entityId` (planned for the interpreters, phase 4); updated `RECEIVED` events (statuses) are not yet exploited.

## Phase 4 notes (agent runtimes)

- **One process, one thread per agent** (`python -m orchestra.runtime`): wake-up via `/ws/wake`, catch-up via `/inbox/pending`, only one task at a time per agent (the per-`entityId` ordering of the interpreters is therefore guaranteed; no partitioning as long as there is a single interpreter). The runtimes have neither an LLM key nor database access; they call the gateway with their agent's token. PoC simplification: the process derives the tokens from the master key (each `AgentRunner` uses only its own); in production each runtime would receive only its token.
- **Loop**: session (idempotent) → context (the `AgentVersion` prompt, mandate, allowed recipients, KG template catalog, open commitments, chain thread limited to what the agent sent/received) → generation ↔ tools, at most 10 turns → closing (`completed`, `failed`, `input-required`). Each tool is traced by a `ToolCall` (`PRODUCED` to the fact or the message); a denial is returned to the LLM as a tool result and the call is marked `failed`. Budget exhausted / chain suspended / turn limit: session `failed`, no retry.
- **Rule-based gates before the LLM**: commitment already settled → no call. Auditor: `POST /audit/scan` first; the LLM is only called on candidate chains whose state has changed since the last judgement.
- **Auditor**: signals computed in the graph — cycles (GDS projection over a sliding window of exchanges between audited agents, `gds.scc.stream`), repeated messages (mean embedding similarity ≥ 0.92), budget ≥ 80%, rate ≥ 15 messages/min. Access: episodic read of the agents it `AUDITS` (sent messages), never the memories. `ratePerMinute` was raised from 8 to 15 after a real trial: a legitimate analysis of 13 messages in 90 s triggered an unnecessary LLM judgement.
- **Commitments**: `commit` creates `Commitment` + a `once` routine (`rt-commit-<id>`, `misfire = fire`) that re-prompts the debtor at the due date, issued by the creditor if it can write to them. Settling (`fulfills`) deactivates the follow-up; otherwise the rule-based gate avoids an LLM call for an already settled commitment.
- **`launch_modification`**: effect of an irreversible tool, executed by the gateway with a dedicated `kgcurator` user (writes to the KGs only, never exposed to the agents), only if the approval is `approved`, with the arguments *frozen at request time*. New `ProductVersion` (`SUPERSEDES`), part retired (`retiredIn`), `CONTAINS` links replaced (`removedIn`/`addedIn`); query templates ignore retired links. Idempotent per approval. The transaction carries the `chainId`: the bridge picks up the change's chain.
- **Wake-up on decision**: the consumer drops an `approval-decided` system message at the requester and a `chain-suspended` message at the auditor (budget/tokens exhausted).
- **CPA**: `orchestra/runtime/cpa.py` (forward/backward pass, slack, critical path, delay simulation), tested against the seed's forward pass.
- **Seed**: a modified prompt creates a new `AgentVersion` (never a rewrite); the KGs are loaded with `ON CREATE` only (a first version rewrote identical properties and set `VER-1.0` back to `current`, which generated CDC events when re-running `make seed` on a live system).
- **Real trial (Gemini 2.5 Flash)**: incident INC-001 → Quality (qualifies, 3 facts, asks the Coordinator with attached memory) → Coordinator (3 requests, commitment) → Tests/Engineering/Planning (proposal accepted first time, 11-day delay by CPA) → synthesis to the project lead → approval requested (`input-required`) → 2 votes → `launch_modification` → `VER-1.1` in the KG → bridge → interpreter → Tests and Planning woken. ≈ 55 s up to the approval request, ≈ 105 k tokens on the chain (default budget 200 k).
- **Findings**: (1) the raw payload of a KG batch, with its CDC event identifiers, drowned the interpreter (two `set_status`, no publication): the `eventId`s are removed from the text seen by the LLM and the prompt requires publication; (2) the legitimate Engineering ↔ Tests loop did not happen because the first candidate was covered by tests: phase 6 will choose the incident (or the state of the tests) to provoke it; (3) a CDC event is only readable a moment after the commit: the tests allow a settling time.

## Phase 5 notes (interface)

- **Stack**: React 19 + Vite + TypeScript, `@neo4j-nvl/react` 2.0 (`canvas` rendering, robust without WebGL), Framer Motion. NVL 2.0 requires React 19. Labels in French. The interface only talks to its own server (nginx in production, Vite proxy in development): `/api` → gateway, `/stream` → CDC consumer (WebSocket). No LLM key in the browser; only a demo token is kept in `sessionStorage`.
- **Demo login** (`ORCHESTRA_DEMO_LOGIN=1`, enabled by the compose file, disabled by default): you pick a person or the administrator, no password. Never to be enabled outside demos; a real installation would plug in OIDC (`Agent:Person.oidcSub` is provided for). No software agent can log in.
- **Chat**: the inbox of the logged-in person (and what they sent), by conversation (chain). Declaration of a prepared incident (quality engineer), pending approvals with vote (committee, `ACTS_FOR` delegates included).
- **Scene**: 13 workstations, eight avatar states fed by the normalized stream (`avatarState.ts`, tested pure function): Woken (startle, blinking box), Thinking (`set_status` bubble), Using a tool (icon + progress), Sending (envelope to the recipient), Learning (spark to the shelf), Waiting (hourglass, greyed out, persists after the session ends), Error (red, shake), Idle (breathing). On load, the initial state comes from `/graph/state`; the history replayed by the server keeps its real date (event older than 5 s = animation already expired). A "busy" agent with no event for 20 s (Woken only) or 60 s falls back to Idle (runtime stopped).
- **Graph (NVL)**: topology (supervision, subscriptions, allowed sends, audit, KG access), stream (edges lit for 8 s), agent card (version, mandate, tools, routines, commitments, latest statuses and calls), rights (the view rebuilds the `SUPERVISES*` paths + terminal relationship; a test guarantees it shows exactly the scope computed by `/scope`), KG (neighborhood of a part or a task, with `CAN_QUERY` check; retired parts in grey).
- **Timeline**: triggered and upcoming routines, tool calls (start→end bars), votes, commitments, one row per actor.
- **Settings → Models**: administrator only; write-only key (last 4 characters and date redisplayed), test (candidate or saved), replace, delete, model choice. A browser test verifies that the real key from the environment appears neither in the DOM, nor in the browser storages, nor in the gateway responses.
- **Endpoints added**: `/demo/*`, `/chat/messages`, `/approvals`, `/graph/{topology,state,agent,rights,kg}`, `/timeline`. People now have `CAN_QUERY` (ing-qualite, committee: Product KG; project lead: both) so that the KG view respects rights as it does for agents. The supervision views (topology, rights) show *metadata* (who can read what), never the content of the memories.
- **Fixes found by the browser tests**: (1) the "direct" session of a human message was never closed, so the person appeared busy forever: it is now closed in the send transaction; (2) a late response from the Rights view overwrote the current selection (stale requests are now ignored); (3) a CDC cursor older than a recreated database blocked the consumer in an error loop (`FutureIdentifier` / `InvalidIdentifier`): it now restarts from the current position, with a warning and a `cursorResets` counter.
- **Tests**: 22 unit tests (Vitest: avatar states, event clock, graph transformations), 6 browser tests (Playwright/Chromium, against the production build served by nginx, no LLM call) via `make e2e`, which starts from a reset database. Start the interface: `make ui` (http://localhost:15173) or `make app` with the runtimes.

## Phase 6 notes (replay and scenario)

- **Stream reconstruction**: `GET /replay/events` replays the graph as one `UNION ALL` per event type (`replay_events.cypher`), sorted by `t`, in the same normalized format `{t, type, actor, target, payload}` as the live stream. A test guarantees that, on the same sequence (session, status, successful and failed tool calls, learned fact, message, commitment, pending approval then votes), the reconstructed multiset `(type, actor, target)` is **identical** to the stream produced live by the CDC consumer. Accepted approximations: the wake-up is replayed for each inbox owner (a later suspension or quarantine is not replayed); the actor of a chain suspension is the auditor (`SUSPENDED` relationship) or `gateway`.
- **Two defects in the live stream found by this comparison**: the end of a tool call lost the tool name (the `OF` relationship only exists in the creation transaction); the name is now denormalized onto the `ToolCall` (`tool`), so the stream no longer depends on the state from one transaction to the next. The message `kind` is also carried by the live `sent` event (it feeds the chapters).
- **Recording**: a `Run` (`startedAt`, `endedAt`) marks the window to replay (the graph *is* the recording: nothing is duplicated); `POST /replay/runs/{id}/export` freezes the events into `data/scenarios/<name>.json`, a portable, versionable file that survives a database reset. Read access open to people; creation and export reserved to the administrator; file name allow-listed (no directory escape).
- **Player** (`replayEngine.ts`, pure and tested): virtual time × speed (×1, ×2, ×5, ×10, ×20); dead-time compression (a gap of more than 4 s skips to 0.8 s before the next event); the time bar recomputes the state by replaying everything with the events' real dates, then expires outdated animations, then moves the deadlines onto the wall clock (`rebase`); chapters detected in the stream (Incident, Impact analysis, Committee vote, Launch, Governance); agent following (ring on its workstation, the others fade, filtered log). The scene, the graph and the log receive the **same context** as the live view (states, envelopes, recent stream): they cannot tell the difference. The inbox and memory counters are recomputed at the replayed instant.
- **Defects from your demo session, fixed**: (1) the Coordinator, woken on each specialist report, requested committee approval **every time** (3 pending approvals for a single decision); deduplication is now in the gateway (one pending request per agent, tool and chain; the next one returns the existing one) and the prompt forbids repeating the request; (2) a person could not close an unproductive chain: `POST /chains/{id}/close` (human decision, final: no more sends, no resume).
- **Scenario incident**: INC-001 is chosen by the generator (`loop_parts`) to provoke the legitimate loop: the part is covered and shared, its first replacement candidate is covered by no test (Tests refuses it), the second one is (Tests accepts it). The commitment deadlines in the prompts are short (2 and 3 minutes) so that the follow-up arrives during the demo.
- **Real scenario** (`make scenario`, Gemini 2.5 Flash, ≈ 5 minutes, ≈ 200,000 tokens): 17 checks out of 17: incident routed by subscription; impact request; three analyses; **legitimate loop** (2 proposals, 1 refusal, agreement); tests, planning and engineering reports; commitments; **a single** pending approval; 2-of-3 quorum; launch (`VER-1.1`, part removed from the bill of materials); bridge, BOM interpreter, wake-up of Tests and Planning; **commitment follow-up** by timer; governance. Main chain: 28/90 messages, 148 k tokens. Recording: `data/scenarios/scenario-complet.json` (381 events, 5 min 08 s).
- **Governance chapter**: to obtain a truly endless back-and-forth between two LLM agents, the script injects a **faulty version** of Engineering and Tests through the admin API (`AgentVersion` + `SUPERSEDES`, like a real prompt deployment): one proposes without concluding, the other refuses without concluding. The Coordinator did not relay the project lead's request; the script then kicks off the loop with a system message (routine), and says so. The auditor detects the cycle (GDS) and the repetitions (embeddings) after 17 messages (19/50 of the budget), suspends the chain (`audit`), notifies the 5 humans; the project lead closes it; the healthy versions are restored (new versions, never overwritten).
- **Real defect found by the first scenario trial**: Engineering called `query_kg` with `template: "part_info(partId)"` or `"produit/part_info(partId)"` (signature copied from the catalog), got a 404 on every call and exhausted its 10 turns without ever proposing a part. Three fixes: unambiguous prompt catalog (`kg="produit", template="part_info", params={"partId": <str>}` and the instruction "the name alone"), tolerant normalization on the runtime side (prefix, parentheses, graph inferred from the catalog), and a 404 error that lists the valid templates.
- **Known limitations**: the scenario depends on LLM behavior (the script waits for each event with a timeout and reports what is missing rather than failing silently); Engineering may propose the same part twice when woken twice (not fixed, harmless); the Governance chapter is detected by a chain suspension (`error` with `chainId`) or a `chain-suspended` message.

## Phase 6b notes (switching the interface and demo to English)

- **Decision** (2026-11-02): interface, demo content (names and titles of agents and humans, mandates, prompts, incident descriptions, synthetic data) and agent messages in English, for an English demo video. `CLAUDE.md` rule updated. The documentation (spec, these notes, README, `CLAUDE.md`, `PROMPT_CC.md`), the code comments and docstrings, and the tests were then translated into English on the same day. Technical identifiers unchanged (agent ids, database names, topics `kg.produit.raw` and `produit.bom-changes`, KG ids): they come from the spec.
- **What changed**: UI labels (`labels.ts`, tables renamed `*_LABEL`), gateway error messages (visible in the UI and read by the LLMs), tool descriptions, shared instructions and session context of the runtimes, consumer notifications, seed prompts and mandates, names of parts, tests, tasks and incidents. The generator's lists keep the same length and order: the data structure is identical (INC-001 remains part PRT-0102 that provokes the legitimate loop), only the labels change.
- **Defect found when replaying the new recording at ×20**: a brief note (e.g. "I approve") was erased by an event that followed 0.5 s later (real time); it now has its own lifetime (`note`/`noteUntil`), tested.
- **New recording** `data/scenarios/full-scenario.json` (451 events, 5 min 42 s; replaces `scenario-complet.json`): 17 checks out of 17, legitimate loop (2 proposals, 1 refusal), a single approval, launch, follow-up, and governance. Variability observed between two runs: the auditor suspends the faulty loop after 17 messages (first run) or 38 messages (budget 42/50: reduced margin but respected) depending on the LLM's pace and the point in the minute at which its routine runs.
