CYPHER 25
MATCH (a:Agent {id: $agentId})-[:HAS_MEMORY]->(mem:Memory)-[:ASSERTS]->(old:Fact {id: $oldId})
WHERE old.validTo IS NULL
MATCH (s:Session {id: $sessionId, agentId: $agentId})
WITH mem, old, s, datetime() AS now
SET old.validTo = now
CREATE (f:Fact {id: $factId, statement: $statement, embedding: $embedding, confidence: $confidence,
                validFrom: now, memoryId: mem.id, recordedAt: now})
CREATE (mem)-[:ASSERTS]->(f)
CREATE (f)-[:LEARNED_IN]->(s)
CREATE (f)-[:SUPERSEDES]->(old)
RETURN f.id AS id, old.id AS supersedes, now AS at
