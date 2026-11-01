CYPHER 25
MATCH (c:Commitment {status: 'open'}) WHERE c.agentId = $agentId
RETURN c.id AS id, c.toAgent AS toAgent, c.description AS description, c.dueAt AS dueAt
ORDER BY c.dueAt
