// Common schema for the KG databases (kgproduit, kgprojet).
CYPHER 25
DROP CONSTRAINT entity_id IF EXISTS;
CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT assertion_id IF NOT EXISTS FOR (n:Assertion) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ref_key IF NOT EXISTS FOR (n:Ref) REQUIRE (n.db, n.key) IS NODE KEY;
