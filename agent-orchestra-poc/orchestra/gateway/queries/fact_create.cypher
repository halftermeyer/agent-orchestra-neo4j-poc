CYPHER 25
MATCH (a:Agent {id: $agentId})-[:HAS_MEMORY]->(mem:Memory)
MATCH (s:Session {id: $sessionId, agentId: $agentId})
CREATE (f:Fact {id: $factId, statement: $statement, embedding: $embedding, confidence: $confidence,
                validFrom: coalesce(datetime($validFrom), datetime()), memoryId: mem.id, recordedAt: datetime()})
CREATE (mem)-[:ASSERTS]->(f)
CREATE (f)-[:LEARNED_IN]->(s)
WITH f
CALL (f) {
  UNWIND $about AS ab
  MATCH (kg:KnowledgeGraph {dbName: ab.db})
  MERGE (r:Ref:EntityRef {db: ab.db, key: ab.key})
    ON CREATE SET r.label = ab.label, r.labelAt = datetime()
  MERGE (r)-[:IN_KG]->(kg)
  CREATE (f)-[:ABOUT]->(r)
  RETURN count(*) AS nAbout
}
CALL (f) {
  UNWIND $derivedFrom AS did
  MATCH (src:Fact {id: did})
  CREATE (f)-[:DERIVED_FROM]->(src)
  RETURN count(*) AS nDerived
}
RETURN f.id AS id, f.memoryId AS memoryId, f.validFrom AS validFrom, nAbout, nDerived
