# agentic-orchestra — rules for Claude Code

Multi-agent orchestration platform on Neo4j (CDC = bus, graph = memory).
The specification is the source of truth: `docs/spec.md`. Read it entirely before changing any schema or query.

## Code location
- Code goes in `agent-orchestra-poc/` (repository root). `docs/spec.md`, `CLAUDE.md` and `PROMPT_CC.md` stay one level above.
- `agent-orchestra-poc/.env` already exists (`GEMINI_API_KEY`, `LLM_PROVIDER`). Add `.env` to `.gitignore` from the first commit, never display it, never log it. The gateway uses it as the initial value as long as no key has been saved in Settings → Models; the key saved in the UI takes precedence.

## Mandatory stack
- Neo4j Enterprise (official Docker image, `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes`), APOC and GDS plugins. No Aura.
- Python 3.12 backend: FastAPI, the official `neo4j` driver, the `google-genai` SDK. A single `orchestra/` package with separate services: `gateway`, `cdc`, `runtime`.
- UI: React + Vite + TypeScript, `@neo4j-nvl/react` for the graph, Framer Motion for the scene. UI labels, demo content (names, mandates, prompts, synthetic data) and agent messages are in English (decision of 2026-11-02, for the demo video); technical identifiers stay as in the spec (`coordinateur`, `kgproduit`, `kg.produit.raw`…). Everything in the repository is in English since 2026-11-02: documentation (spec, notes, README), code comments and docstrings, tests; only the technical identifiers inherited from the spec stay in French.
- `docker compose` to start everything; `make` for common commands.
- The databases (`orchestra`, `kgproduit`, `kgprojet`, composite `fed`), the users (admin, gateway, cdc) and the CDC activation are created by a versioned, idempotent init script (`db/init/`), never by hand.
- Exposed ports: 17474 (HTTP) and 17687 (Bolt), so as not to clash with a local Neo4j instance that is already running.

## Non-negotiable rules
1. Cypher 25 everywhere (`CYPHER 25` at the top). No `elementId` as a business key.
2. Agents never touch the database: every read/write goes through the gateway, with frozen, parameterized queries stored in `orchestra/gateway/queries/*.cypher`. No Cypher built by concatenation.
3. The `agentId` comes from the authentication context (one service token per runtime), never from an argument supplied by the LLM.
4. Append-only writes: no linked list, no `LAST` pointer. Day buckets (`InboxDay`, `WorkDay`) with `MERGE` on a node key.
5. We never overwrite: every state transition keeps its date (`submittedAt`, `workingAt`, `completedAt`, `startedAt`, `endedAt`…), which replay depends on.
6. Rights = paths (ReBAC), with the whitelisted grammar of the spec. Every new source of sharing is an explicit branch of the scope query.
7. Secrets (Gemini key) go neither in the graph, nor in the repository, nor in the logs, nor in the browser. Encrypted storage on the gateway side, master key in `ORCHESTRA_MASTER_KEY`.
8. Every agent write sets `txMetadata` (`agentId`, `chainId`).
9. The CDC consumer is idempotent and persists one cursor per database.
10. The per-chain budget is checked synchronously by the gateway on every send.

## How to work
- Proceed in phases (see `PROMPT_CC.md`). At the end of each phase: green tests, a summary of what was done, any deviations from the spec, then **stop and wait for my approval**.
- If a Neo4j feature does not behave as the spec assumes, do not work around it silently: note it in `docs/spikes.md` and propose an alternative.
- Tests: `pytest` for the backend, with a test Neo4j instance (testcontainers or the compose). The rights non-leak tests are mandatory.
- Small, explicit commits, in English.
