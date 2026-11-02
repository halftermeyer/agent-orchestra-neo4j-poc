CYPHER 25
MATCH (r:Run {id: $id})
RETURN r.id AS id, r.name AS name, r.note AS note, r.chainId AS chainId, r.startedAt AS startedAt, r.endedAt AS endedAt
