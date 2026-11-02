CYPHER 25
MATCH (a:Agent {id: $agentId})-[cu:CAN_USE]->(t:Tool {name: $tool}) WHERE t.effect = 'irreversible'
MATCH (a)-[:CAN_SEND_TO]->(e:Inbox {id: $electorate})
MATCH (s:Session {id: $sessionId, agentId: $agentId}) WHERE s.closedAt IS NULL
CREATE (tc:ToolCall {idempotencyKey: $key, status: 'input-required', startedAt: datetime(), inputRequiredAt: datetime(), agentId: a.id, tool: t.name, args: $args})
CREATE (s)-[:CALLED]->(tc)
CREATE (tc)-[:OF]->(t)
CREATE (ap:Approval {id: $approvalId, policy: cu.approval, quorum: $quorum, size: $size, status: 'pending',
                     requestedAt: datetime(), electorate: e.id, requestedBy: a.id})
CREATE (ap)-[:FOR]->(tc)
RETURN ap.id AS id, ap.status AS status, ap.quorum AS quorum, ap.size AS size,
       COUNT { MATCH (p:Agent:Person)-[:HAS_INBOX]->(e) } AS electors
