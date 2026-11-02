CYPHER 25
CREATE (r:Run {id: $id, name: $runName, note: $note, chainId: $chainId, startedAt: datetime(), createdBy: $by})
RETURN r.id AS id, r.startedAt AS startedAt
