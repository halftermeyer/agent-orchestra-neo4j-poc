CYPHER 25
MATCH (a:Agent {id: $agentId})-[:HAS_WORKSPACE]->(w:Workspace)
MERGE (s:Session {triggerMsgId: $triggerMsgId})
  ON CREATE SET s.id = 'ses:' + $triggerMsgId, s.openedAt = datetime(), s.agentId = a.id, s.chainId = $chainId
WITH w, s
MERGE (d:Day:WorkDay {workspaceId: w.id, date: date(s.openedAt)})
MERGE (w)-[:HAS_DAY]->(d)
MERGE (d)-[:OPENED]->(s)
RETURN s.id AS id, s.chainId AS chainId
