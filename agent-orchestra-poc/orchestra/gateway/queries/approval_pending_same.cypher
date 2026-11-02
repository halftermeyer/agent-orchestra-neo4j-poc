CYPHER 25
MATCH (ap:Approval {status: 'pending', requestedBy: $agentId})-[:FOR]->(tc:ToolCall)-[:OF]->(:Tool {name: $tool})
MATCH (tc)<-[:CALLED]-(:Session {chainId: $chainId})
RETURN ap.id AS id, ap.status AS status, ap.quorum AS quorum, ap.size AS size, tc.idempotencyKey AS toolCallKey
ORDER BY ap.requestedAt
LIMIT 1
