CYPHER 25
MATCH (r:Run)
RETURN r.id AS id, r.name AS name, r.note AS note, r.chainId AS chainId, r.startedAt AS startedAt, r.endedAt AS endedAt
ORDER BY startedAt DESC
