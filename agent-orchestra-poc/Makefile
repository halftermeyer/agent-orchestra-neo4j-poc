.PHONY: up down reset init seed test shell keygen gateway app
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
	docker compose down -v

keygen:
	@grep -q '^ORCHESTRA_MASTER_KEY=' .env || (printf '\nORCHESTRA_MASTER_KEY=%s\n' "$$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> .env && echo "clé maître générée dans .env")
gateway: init keygen
	docker compose --profile app up -d --build gateway
app: init keygen
	docker compose --profile app up -d --build gateway cdc runtime
