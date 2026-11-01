CYPHER 25
MATCH (s:Session {id: $sessionId})
RETURN s.id AS id, s.agentId AS agentId, s.chainId AS chainId, s.closedAt AS closedAt
