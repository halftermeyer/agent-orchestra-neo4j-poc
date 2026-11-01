CYPHER 25
MATCH (m:Message {id: $messageId}), (mem:Memory {id: $memoryId})
CREATE (m)-[g:CAN_READ {mode: $mode, asOf: m.createdAt, until: datetime($until), private: $private, grantedBy: $agentId}]->(mem)
RETURN g.asOf AS asOf, g.until AS until
