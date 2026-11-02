.PHONY: up down reset init seed test shell keygen gateway app ui e2e scenario
up:
	docker compose up -d --wait neo4j
init: up
	docker compose --profile tools run --rm init
seed: init
	docker compose --profile tools run --rm tools python -m orchestra.seed
test: seed
	docker compose --profile tools run --rm tools pytest -q
down:
	docker compose down
reset:
	docker compose --profile app --profile tools down -v

keygen:
	@grep -q '^ORCHESTRA_MASTER_KEY=' .env || (printf '\nORCHESTRA_MASTER_KEY=%s\n' "$$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> .env && echo "clé maître générée dans .env")
gateway: init keygen
	docker compose --profile app up -d --build gateway
app: init keygen
	docker compose --profile app up -d --build gateway cdc runtime ui

# Interface seule (sans LLM) : http://localhost:15173
ui: init keygen
	docker compose --profile app up -d --build gateway cdc ui
# Tests de navigateur sur une base propre, sans runtimes (donc sans appel LLM)
e2e: keygen
	docker compose --profile app --profile tools down -v
	$(MAKE) seed
	docker compose --profile app up -d --build gateway cdc ui
	cd ui && npm ci && npx playwright install chromium && npx playwright test

# Scénario complet avec les vrais agents (Gemini) : base remise à zéro, pile complète, enregistrement exporté dans data/scenarios/
scenario: keygen
	docker compose --profile app --profile tools down -v
	$(MAKE) seed
	docker compose --profile app up -d --build gateway cdc runtime ui
	@until curl -sf localhost:18001/health >/dev/null && curl -sf localhost:18000/health >/dev/null; do sleep 1; done; sleep 15
	docker compose --profile app exec -T cdc python scripts/run_scenario.py
