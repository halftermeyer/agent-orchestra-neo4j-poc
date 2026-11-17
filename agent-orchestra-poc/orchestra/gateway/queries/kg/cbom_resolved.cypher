CYPHER 25
// 5.2 of the configurable-bom page, as rows
MATCH (s)-[r:RESOLVED_LINK {id_variant: $id_variant}]->(t)
RETURN s.id AS source, r.rel_type AS relType, r.qty AS qty, t.id AS target
ORDER BY source, target
