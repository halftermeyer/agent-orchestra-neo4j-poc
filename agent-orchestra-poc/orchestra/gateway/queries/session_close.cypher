CYPHER 25
MATCH (s:Session {id: $sessionId, agentId: $agentId})
SET s.closedAt = coalesce(s.closedAt, datetime())
WITH s
OPTIONAL MATCH (s)-[:TRIGGERED_BY]->(m:Message)
OPTIONAL MATCH (:Agent {id: s.agentId})-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m)
SET r.status = $status,
    r.completedAt = CASE WHEN $status = 'completed' THEN coalesce(r.completedAt, datetime()) ELSE r.completedAt END,
    r.failedAt = CASE WHEN $status = 'failed' THEN coalesce(r.failedAt, datetime()) ELSE r.failedAt END,
    r.canceledAt = CASE WHEN $status = 'canceled' THEN coalesce(r.canceledAt, datetime()) ELSE r.canceledAt END,
    r.inputRequiredAt = CASE WHEN $status = 'input-required' THEN coalesce(r.inputRequiredAt, datetime()) ELSE r.inputRequiredAt END
RETURN s.id AS id, s.closedAt AS closedAt
