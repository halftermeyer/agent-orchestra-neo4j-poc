CYPHER 25
MATCH (r:Run {id: $id})
SET r.endedAt = coalesce(r.endedAt, datetime())
RETURN r.id AS id, r.startedAt AS startedAt, r.endedAt AS endedAt
