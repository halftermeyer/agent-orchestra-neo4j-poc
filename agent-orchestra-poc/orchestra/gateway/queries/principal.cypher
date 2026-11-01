CYPHER 25
MATCH (a:Agent {id: $id})
RETURN a.id AS id, labels(a) AS labels, a.role AS role, coalesce(a.quarantined, false) AS quarantined
