CYPHER 25
// 5.6 of the configurable-bom page; returns the (source, ConfigGroup) pair instead of the path. Deviation: the page's
// pattern is undirected (-[rs]-*), which enumerates back-and-forth trails and exhausts transaction memory on the PoC
// BOM; after the GC (5.4) every resolved node is reachable downstream from the Product, so ->* is equivalent.
// Find unresolved ConfigGroups
MATCH path = (:Product)-[rs:RESOLVED_LINK {id_variant: $id_variant}]->*(x)-[:REQUIRES]->(y:ConfigGroup)
WHERE NOT EXISTS {(x)-[:RESOLVED_LINK {id_variant: $id_variant}]->(y)}
RETURN DISTINCT x.id AS source, y.id AS group, y.desc AS desc
ORDER BY source, group
