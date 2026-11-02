CYPHER 25
MATCH (c:Commitment) WHERE c.createdAt > datetime() - duration({hours: $hours})
RETURN c.agentId AS actor, c.toAgent AS toAgent, c.description AS description, c.status AS status, c.createdAt AS at, c.dueAt AS dueAt, c.fulfilledAt AS fulfilledAt
ORDER BY at DESC LIMIT 200
