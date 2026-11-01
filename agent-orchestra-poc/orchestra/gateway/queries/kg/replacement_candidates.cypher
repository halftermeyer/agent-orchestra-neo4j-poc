CYPHER 25
MATCH (x:Part {id: $partId})
MATCH (c:Part {level: x.level, family: x.family}) WHERE c.id <> x.id AND c.retiredIn IS NULL
RETURN c.id AS id, c.name AS name, c.revision AS revision, c.criticality AS criticality
ORDER BY criticality, id
LIMIT $limit
