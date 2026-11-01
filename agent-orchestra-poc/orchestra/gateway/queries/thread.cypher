CYPHER 25
MATCH (m:Message {chainId: $chainId})
WHERE m.from = $agentId OR EXISTS { (:Agent {id: $agentId})-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m) }
RETURN m.id AS id, m.from AS from, m.performative AS performative, m.body AS body, m.payloadJson AS payloadJson, m.createdAt AS createdAt,
       COLLECT { MATCH (i:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m) RETURN i.id ORDER BY i.id } AS to
ORDER BY createdAt DESC
LIMIT $limit
