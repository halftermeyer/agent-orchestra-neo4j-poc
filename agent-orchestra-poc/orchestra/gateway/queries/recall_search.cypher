CYPHER 25
MATCH (f:Fact)
  SEARCH f IN (VECTOR INDEX fact_embedding FOR $embedding WHERE f.memoryId IN $memoryIds LIMIT $candidates) SCORE AS score
WITH f, score
WHERE any(sc IN $scopes WHERE sc.id = f.memoryId AND f.recordedAt <= sc.asOf AND f.validFrom <= sc.asOf
                              AND (f.validTo IS NULL OR f.validTo > sc.asOf))
RETURN f.id AS id, f.statement AS statement, f.memoryId AS memoryId, f.confidence AS confidence,
       f.validFrom AS validFrom, f.validTo AS validTo, score
ORDER BY score DESC
LIMIT $k
