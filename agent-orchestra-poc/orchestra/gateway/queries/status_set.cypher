CYPHER 25
MATCH (s:Session {id: $sessionId, agentId: $agentId}) WHERE s.closedAt IS NULL
CREATE (s)-[:STATUS]->(u:StatusUpdate {id: $id, text: $text, at: datetime()})
RETURN u.id AS id, u.at AS at
