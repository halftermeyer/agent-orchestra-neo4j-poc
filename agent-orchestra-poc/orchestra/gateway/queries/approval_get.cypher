CYPHER 25
MATCH (ap:Approval {id: $approvalId})-[:FOR]->(tc:ToolCall)
RETURN ap.id AS id, ap.status AS status, ap.policy AS policy, ap.quorum AS quorum, ap.size AS size, ap.electorate AS electorate,
       ap.requestedBy AS requestedBy, tc.idempotencyKey AS toolCallKey,
       head(COLLECT { MATCH (tc)<-[:CALLED]-(s:Session) RETURN s.chainId }) AS chainId, tc.status AS toolCallStatus,
       COLLECT { MATCH (p:Agent)-[v:VOTED]->(ap) RETURN {personId: v.personId, decision: v.decision, at: v.at, onBehalfOf: v.onBehalfOf} } AS votes
