CYPHER 25
CALL () {
  // sent: one envelope per recipient (inbox owner) or to the topic
  MATCH (i:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m:Message)
  WITH i, m, r, COLLECT { MATCH (a:Agent)-[:HAS_INBOX]->(i) RETURN a.id } AS owners
  UNWIND (CASE WHEN i:Topic THEN [i.id] ELSE owners END) AS target
  RETURN r.submittedAt AS t, 'sent' AS type, m.from AS actor, target,
         {messageId: m.id, performative: m.performative, chainId: m.chainId, inbox: i.id, topic: i:Topic, pj: m.payloadJson} AS payload
  UNION ALL
  // woken: at receipt creation, for each owner (later suspension or quarantine is not replayed)
  MATCH (a:Agent)-[:HAS_INBOX]->(i:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m:Message)
  WHERE NOT i:Topic
  RETURN r.submittedAt AS t, 'woken' AS type, a.id AS actor, null AS target,
         {messageId: m.id, performative: m.performative, chainId: m.chainId, inbox: i.id, pj: m.payloadJson} AS payload
  UNION ALL
  MATCH (s:Session)-[:STATUS]->(u:StatusUpdate)
  RETURN u.at AS t, 'status' AS type, s.agentId AS actor, null AS target, {text: u.text} AS payload
  UNION ALL
  MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(tl:Tool) WHERE tc.inputRequiredAt IS NULL
  RETURN tc.startedAt AS t, 'tool.start' AS type, tc.agentId AS actor, tl.name AS target, {key: tc.idempotencyKey, status: 'working'} AS payload
  UNION ALL
  MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(tl:Tool) WHERE tc.inputRequiredAt IS NOT NULL
  RETURN tc.inputRequiredAt AS t, 'waiting' AS type, tc.agentId AS actor, tl.name AS target, {key: tc.idempotencyKey, status: 'input-required'} AS payload
  UNION ALL
  MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(tl:Tool) WHERE tc.inputRequiredAt IS NOT NULL AND tc.workingAt IS NOT NULL
  RETURN tc.workingAt AS t, 'tool.start' AS type, tc.agentId AS actor, tl.name AS target, {key: tc.idempotencyKey, status: 'working', resumed: true} AS payload
  UNION ALL
  MATCH (:Session)-[:CALLED]->(tc:ToolCall)-[:OF]->(tl:Tool) WHERE tc.endedAt IS NOT NULL
  RETURN tc.endedAt AS t, CASE tc.status WHEN 'failed' THEN 'error' ELSE 'tool.end' END AS type, tc.agentId AS actor, tl.name AS target,
         {key: tc.idempotencyKey, status: tc.status, error: tc.error} AS payload
  UNION ALL
  MATCH (f:Fact)
  RETURN f.recordedAt AS t, 'learned' AS type, replace(f.memoryId, 'mem:', '') AS actor, f.memoryId AS target,
         {factId: f.id, statement: left(f.statement, 140)} AS payload
  UNION ALL
  MATCH (p:Agent)-[v:VOTED]->(ap:Approval)
  RETURN v.at AS t, 'vote' AS type, p.id AS actor, ap.id AS target, {decision: v.decision, onBehalfOf: v.onBehalfOf} AS payload
  UNION ALL
  MATCH (c:Commitment)
  RETURN c.createdAt AS t, 'waiting' AS type, c.agentId AS actor, c.toAgent AS target,
         {commitmentId: c.id, dueAt: toString(c.dueAt), description: left(c.description, 140)} AS payload
  UNION ALL
  MATCH (s:Session) WHERE s.closedAt IS NOT NULL
  RETURN s.closedAt AS t, 'idle' AS type, s.agentId AS actor, null AS target, {session: s.id} AS payload
  UNION ALL
  MATCH (c:Chain) WHERE c.suspendedAt IS NOT NULL
  RETURN c.suspendedAt AS t, 'error' AS type, coalesce(head([(a:Agent)-[:SUSPENDED]->(c) | a.id]), 'gateway') AS actor, c.id AS target,
         {chainId: c.id, reason: c.suspendReason} AS payload
  UNION ALL
  MATCH (x:Agent) WHERE x.quarantinedAt IS NOT NULL
  RETURN x.quarantinedAt AS t, 'error' AS type, head([(a:Agent)-[:QUARANTINED]->(x) | a.id]) AS actor, x.id AS target, {reason: 'quarantine'} AS payload
}
WITH t, type, actor, target, payload
WHERE t >= datetime($from) AND t <= datetime($to)
RETURN t, type, actor, target, payload
ORDER BY t
LIMIT $limit
