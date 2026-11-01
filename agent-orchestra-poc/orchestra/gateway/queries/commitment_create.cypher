CYPHER 25
MATCH (a:Agent {id: $agentId})-[:CAN_USE]->(:Tool {name: 'commit'})
MATCH (s:Session {id: $sessionId, agentId: $agentId}) WHERE s.closedAt IS NULL
MATCH (to:Agent {id: $to}) WHERE to <> a
CREATE (c:Commitment {id: $id, agentId: a.id, toAgent: to.id, description: $description, dueAt: datetime($dueAt),
                      status: 'open', createdAt: datetime(), chainId: s.chainId})
CREATE (a)-[:COMMITTED]->(c)
CREATE (c)-[:MADE_IN]->(s)
RETURN c.id AS id, c.dueAt AS dueAt
