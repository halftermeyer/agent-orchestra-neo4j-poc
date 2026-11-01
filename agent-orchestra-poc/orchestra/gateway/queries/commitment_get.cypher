CYPHER 25
MATCH (c:Commitment {id: $id}) WHERE c.agentId = $agentId OR c.toAgent = $agentId
RETURN c.id AS id, c.agentId AS agentId, c.toAgent AS toAgent, c.description AS description, c.dueAt AS dueAt,
       c.status AS status, c.createdAt AS createdAt, c.fulfilledAt AS fulfilledAt
