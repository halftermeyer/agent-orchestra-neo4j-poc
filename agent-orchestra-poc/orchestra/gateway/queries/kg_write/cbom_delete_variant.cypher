CYPHER 25
// Scratch variants are not kept: delete every RESOLVED_LINK of the variant
MATCH ()-[r:RESOLVED_LINK {id_variant: $id_variant}]->()
DELETE r
RETURN count(*) AS deleted
