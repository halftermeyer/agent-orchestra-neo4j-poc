CYPHER 25
MATCH (r:EntityRef {db: $db, key: $key})
SET r.label = $label, r.labelAt = datetime()
RETURN r.key AS key
