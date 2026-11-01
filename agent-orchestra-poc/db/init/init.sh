#!/bin/bash
# Init idempotent : bases, utilisateurs, CDC, schémas. Lancé par `make init` (service compose `init`).
set -euo pipefail
URI="${NEO4J_URI:-bolt://neo4j:7687}"
SU=(cypher-shell -a "$URI" -u neo4j -p "${NEO4J_PASSWORD:-orchestra-dev-pw}")

until "${SU[@]}" -d system "SHOW DATABASES" >/dev/null 2>&1; do echo "attente de Neo4j…"; sleep 2; done

"${SU[@]}" -d system \
  --param "adminPw => '${NEO4J_ADMIN_PASSWORD:-admin-dev-pw}'" \
  --param "gatewayPw => '${NEO4J_GATEWAY_PASSWORD:-gateway-dev-pw}'" \
  --param "cdcPw => '${NEO4J_CDC_PASSWORD:-cdc-dev-pw}'" \
  --param "kgPw => '${NEO4J_KGCURATOR_PASSWORD:-kgcurator-dev-pw}'" \
  -f /init/system.cypher

# Le CDC redémarre la base après ALTER ... txLogEnrichment : attendre qu'elle réponde.
for db in orchestra kgproduit kgprojet; do
  until "${SU[@]}" -d "$db" "CALL db.cdc.current() YIELD id RETURN id" >/dev/null 2>&1; do sleep 2; done
done

"${SU[@]}" -d orchestra -f /db/schema.cypher
"${SU[@]}" -d kgproduit -f /db/schema_kg.cypher
"${SU[@]}" -d kgprojet -f /db/schema_kg.cypher
echo "init OK"
