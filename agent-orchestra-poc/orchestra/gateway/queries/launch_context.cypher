CYPHER 25
MATCH (tc:ToolCall {idempotencyKey: $key, agentId: $agentId})-[:OF]->(:Tool {name: 'launch_modification'})
MATCH (ap:Approval)-[:FOR]->(tc)
RETURN tc.status AS toolCallStatus, tc.args AS args, ap.status AS approvalStatus, ap.id AS approvalId
