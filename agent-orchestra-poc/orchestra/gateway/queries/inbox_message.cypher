CYPHER 25
MATCH (a:Agent {id: $agentId})-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m:Message {id: $messageId})
RETURN DISTINCT m.id AS id, m.from AS from, m.performative AS performative, m.body AS body, m.payloadJson AS payloadJson,
       m.chainId AS chainId, m.conversationId AS conversationId, m.createdAt AS createdAt,
       EXISTS { (m)-[g:CAN_READ]->(:Memory) WHERE g.until > datetime() } AS hasSharedMemory
