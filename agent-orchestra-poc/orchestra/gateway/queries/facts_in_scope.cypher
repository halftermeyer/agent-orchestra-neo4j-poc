CYPHER 25
UNWIND $scopes AS sc
MATCH (f:Fact {memoryId: sc.id})
WHERE f.id IN $ids AND f.recordedAt <= sc.asOf AND f.validFrom <= sc.asOf AND (f.validTo IS NULL OR f.validTo > sc.asOf)
RETURN DISTINCT f.id AS id
