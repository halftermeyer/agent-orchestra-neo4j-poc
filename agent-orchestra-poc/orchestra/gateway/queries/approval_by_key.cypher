CYPHER 25
MATCH (ap:Approval)-[:FOR]->(tc:ToolCall {idempotencyKey: $key, agentId: $agentId})
RETURN ap.id AS id, ap.status AS status
