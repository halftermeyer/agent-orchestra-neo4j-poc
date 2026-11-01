#!/bin/sh
# usage: cy.sh <db> <user> <pw> "<query>"
docker exec -i orchestra-neo4j cypher-shell -u "$2" -p "$3" -d "$1" --format plain "$4"
