# Agent orchestration on Neo4j — PoC

A multi-agent orchestration platform where **Neo4j is both the bus (CDC) and the memory**: inboxes, messages, routines, rights as paths (ReBAC), federation of knowledge graphs, governance (budget, auditor, human approvals) and traceability. Scenario: a field incident triggers a product modification. The UI, the demo content and the agents' messages are in English (demo video); the documentation is in English too, while code comments are still mostly in French.

- Specification: [`docs/spec.md`](docs/spec.md) — Project rules: [`CLAUDE.md`](CLAUDE.md) — Spikes and deviations: [`docs/spikes.md`](docs/spikes.md)
- Code: [`agent-orchestra-poc/`](agent-orchestra-poc/) (gateway, CDC consumer, agent runtimes, React UI)

## Getting started

Requirements: Docker, `make`, Node 22 (browser tests). Create `agent-orchestra-poc/.env` with `GEMINI_API_KEY=…` and `LLM_PROVIDER=gemini` (never versioned), then:

```bash
cd agent-orchestra-poc
make keygen      # generates ORCHESTRA_MASTER_KEY in .env (without displaying it)
make seed        # Neo4j Enterprise (APOC, GDS), databases, users, CDC, schema, synthetic data
make app         # gateway, CDC consumer, agent runtimes, UI → http://localhost:15173
```

Neo4j: HTTP 17474, Bolt 17687. Gateway: 18000. CDC consumer: 18001. `make ui` starts the UI without the runtimes (so no LLM calls); `make reset` wipes everything.

## Replay and scenario

The **Replay** tab replays the event stream rebuilt from the graph, or a recording file, on the scene, the graph and the log: play/pause, speed ×1 to ×20, time bar, idle-time compression, chapters (incident, impact analysis, committee vote, launch, governance), follow an agent. A real scenario is provided: [`agent-orchestra-poc/data/scenarios/full-scenario.json`](agent-orchestra-poc/data/scenarios/full-scenario.json) (from the incident to governance, with the legitimate loop, the vote, the launch, the reminder and the auditor suspending an endless loop).

```bash
make scenario   # resets the database, starts the stack and replays the full scenario with the real agents (≈ 5 min, ≈ 200,000 Gemini tokens)
```

## Tests

```bash
make test   # pytest: schema, gateway, rights non-leak tests, CDC, runtimes (test Neo4j)
make e2e    # Playwright on a clean database, no LLM; UI unit tests: cd ui && npm test
```

Neo4j Enterprise license: the image is used with `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes` (check this for your use). The compose default passwords are local development values.
