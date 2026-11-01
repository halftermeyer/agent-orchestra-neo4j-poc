CYPHER 25
MATCH (a:Agent {id: $agentId})-[:HAS_INBOX]->(i:Inbox)-[:HAS_DAY]->(:InboxDay)-[r:RECEIVED {status: 'submitted'}]->(m:Message)
RETURN m.id AS messageId, i.id AS inbox, m.chainId AS chainId, r.submittedAt AS submittedAt
ORDER BY submittedAt, messageId
LIMIT $limit
