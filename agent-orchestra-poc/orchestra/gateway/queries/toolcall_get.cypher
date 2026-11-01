CYPHER 25
MATCH (tc:ToolCall {idempotencyKey: $key, agentId: $agentId})
RETURN tc.idempotencyKey AS key, tc.status AS status, tc.startedAt AS startedAt, tc.endedAt AS endedAt, tc.tokens AS tokens,
       head(COLLECT { MATCH (tc)<-[:FOR]-(ap:Approval) RETURN ap.id }) AS approvalId
