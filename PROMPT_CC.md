# Launch prompt for Claude Code

Read `CLAUDE.md`, then `docs/spec.md` in full. The code goes in `agent-orchestra-poc/`. You are building the PoC described in the spec, phase by phase. After each phase, stop and wait for my approval.

## Phase 0 — Spikes (verify the spec's assumptions)
Set up a minimal `docker-compose.yml` with Neo4j Enterprise (APOC, GDS), then verify and document in `docs/spikes.md`, with the exact Neo4j version:
- `MATCH ACYCLIC` and `MATCH ANY` on `-[:SUPERVISES]->*` (results on a small graph with a cycle);
- CDC activation (`ALTER DATABASE … SET OPTION txLogEnrichment 'FULL'`), `db.cdc.current`/`db.cdc.query`, minimal privileges of a user dedicated to the CDC;
- composite database `fed` with aliases to `orchestra`, `kgproduit`, `kgprojet`, and `USE graph.byName(...)` with a name computed inside a `CALL`;
- vector index with a filter (`SEARCH` if available, otherwise post-filter);
- `apoc.util.validate` inside a write.
Also measure the write → CDC event latency with polling at 100, 250 and 500 ms.

## Phase 1 — Schema and data
- The spec's constraints and indexes (`db/schema.cypher`), applied at startup.
- Seed of the orchestration database: the scenario's agents (Coordinator, Quality, Engineering, Testing, Planning, KG Bridge, BOM Interpreter, Auditor) and people (quality engineer, a 3-person committee with a shared inbox, project manager), mandates, versions, inboxes, topics (`incidents`, `kg.produit.raw`, `produit.bom-changes`), `SUPERVISES`, `CAN_SEND_TO`, `CAN_USE`, routines.
- Deterministic synthetic data generator (fixed seed): Product KG (~200 parts over 3-4 BOM levels, ~50 tests with coverage, versions), Project KG (~30 tasks with dependencies, resources), ~10 planned incidents. Fictional product, no real names.

## Phase 2 — Gateway
- FastAPI API: send a message (with attached memory, multiple recipients, `CAN_SEND_TO` check, chain budget), idempotent session opening, `set_status`, `Fact` recording/revision, memory retrieval (ReBAC scope + vector search + `asOf` filter), traced tool calls (`ToolCall`, `idempotencyKey`), approvals and votes, KG reads (query templates), federated query.
- LLM provider abstraction (interface: generation, tool calling, embeddings, token counting) with a Gemini implementation.
- Settings → Models: endpoints to save (write-only), test (model list), replace and delete the key; encrypted storage.
- Access log in the graph.
- Non-leak tests (a peer's memory, `private`, later `snapshot`, expired share, supervision of a `:Person`).

## Phase 3 — CDC consumer
- Polling with a persistent cursor per database; waking the runtimes; topic routing (structured filters); routine scheduler (`cron`, `once`, `event`, `misfire = skip`); KG bridge (one message per transaction); `EntityRef` synchronization.
- Normalized event stream `{t, type, actor, target, payload}` broadcast over WebSocket.

## Phase 4 — Agent runtimes
- Generic LLM agent loop with the tools: `send_message`, `set_status`, `remember`, `recall`, `query_kg`, `commit`, `request_approval`, and for Planning a CPA tool (forward/backward pass, critical path, delay simulation).
- Rule-based agents (KG bridge) and the auditor (GDS signals + LLM judgement on candidates, power limited to suspension).
- Scenario prompts and mandates.

## Phase 5 — UI
Chat (the signed-in person's inbox, user selection for the demo), scene with avatars animated according to the spec's states, NVL graph (topology, flow, agent card, rights with highlighted path, KG), timeline, Settings → Models.

## Phase 6 — Replay and scenario
Endpoint rebuilding the stream from the graph, playback controls (speed ×1–×20, time bar, idle-time compression, chapters, follow an agent). Run the full scenario end to end, including the legitimate loop and the governance chapter, and record it for replay.

Start with phase 0.
