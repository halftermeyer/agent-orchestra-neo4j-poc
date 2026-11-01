CYPHER 25
MATCH (m:Message {id: $messageId})
RETURN m.id AS id, m.from AS from, m.chainId AS chainId, m.performative AS performative, m.body AS body,
       m.payloadJson AS payloadJson, m.createdAt AS createdAt, m.conversationId AS conversationId,
       head(COLLECT { MATCH (m)-[:IN_CHAIN]->(c:Chain) RETURN c.status }) AS chainStatus
