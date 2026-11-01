CYPHER 25
MATCH (tc:ToolCall {idempotencyKey: $key, agentId: $agentId}) WHERE tc.status = 'working'
SET tc.status = $status, tc.endedAt = datetime(), tc.tokens = $tokens, tc.error = $error
WITH tc
CALL (tc) {
  OPTIONAL MATCH (:Agent {id: $agentId})-[:HAS_MEMORY]->(:Memory)-[:ASSERTS]->(f:Fact {id: $factId})
  WITH tc, f WHERE f IS NOT NULL
  CREATE (tc)-[:PRODUCED]->(f)
  RETURN count(*) AS nf
}
CALL (tc) {
  OPTIONAL MATCH (mm:Message {id: $messageId, from: $agentId})
  WITH tc, mm WHERE mm IS NOT NULL
  CREATE (tc)-[:PRODUCED]->(mm)
  RETURN count(*) AS nm
}
RETURN tc.status AS status, tc.endedAt AS endedAt
