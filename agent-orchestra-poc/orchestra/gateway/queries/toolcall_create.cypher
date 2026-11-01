CYPHER 25
MATCH (a:Agent {id: $agentId})-[:CAN_USE]->(t:Tool {name: $tool})
MATCH (s:Session {id: $sessionId, agentId: $agentId}) WHERE s.closedAt IS NULL
CREATE (tc:ToolCall {idempotencyKey: $key, status: 'working', startedAt: datetime(), workingAt: datetime(), agentId: a.id, args: $args})
CREATE (s)-[:CALLED]->(tc)
CREATE (tc)-[:OF]->(t)
RETURN tc.idempotencyKey AS key, tc.status AS status
