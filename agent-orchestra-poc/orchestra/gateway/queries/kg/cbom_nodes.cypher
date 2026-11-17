CYPHER 25
// Display data of CBOM nodes (parts, assemblies, config groups)
MATCH (n:Entity) WHERE n.id IN $ids
RETURN n.id AS id, coalesce(n.name, n.desc) AS name, [l IN labels(n) WHERE l <> 'Entity'] AS labels,
       n.cost AS cost, n.weight AS weight, n.family AS family
