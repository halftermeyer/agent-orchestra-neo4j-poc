CYPHER 25
MATCH (r:EntityRef {db: $db, key: $key})
SET r.deletedAt = coalesce(r.deletedAt, datetime())
RETURN r.key AS key
