CYPHER 25
MATCH (a:Agent:SoftwareAgent {id: $agentId})-[:HAS_WORKSPACE]->(w:Workspace)
MATCH (a)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED]->(m:Message {id: $messageId})
MATCH (a)-[:CURRENT]->(v:AgentVersion)
WITH DISTINCT a, w, m, v, r LIMIT 1
SET r.status = CASE WHEN r.status = 'submitted' THEN 'working' ELSE r.status END,
    r.workingAt = coalesce(r.workingAt, datetime())
WITH a, w, m, v
MERGE (s:Session {triggerMsgId: $triggerMsgId})
  ON CREATE SET s.id = 'ses:' + $triggerMsgId, s.openedAt = datetime(), s.agentId = a.id, s.chainId = coalesce(m.chainId, m.id)
WITH a, w, m, v, s
MERGE (d:Day:WorkDay {workspaceId: w.id, date: date(s.openedAt)})
MERGE (w)-[:HAS_DAY]->(d)
MERGE (d)-[:OPENED]->(s)
MERGE (s)-[:TRIGGERED_BY]->(m)
MERGE (s)-[:RAN_AS]->(v)
RETURN s.id AS id, s.agentId AS agentId, s.chainId AS chainId, s.openedAt AS openedAt, s.closedAt AS closedAt
