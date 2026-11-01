CYPHER 25
OPTIONAL MATCH (e:Entity {id: $key})
RETURN e IS NOT NULL AS exists, labels(e) AS labels
