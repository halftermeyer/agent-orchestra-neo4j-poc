CYPHER 25
MATCH (aud:Agent {id: $agentId})-[:AUDITS]->(a:Agent)
MATCH (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(:Session)-[:SENT]->(m:Message {chainId: $chainId})
RETURN m.id AS id, a.id AS from, m.performative AS performative, left(m.body, 400) AS body, m.createdAt AS createdAt,
       COLLECT { MATCH (i:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m) RETURN i.id ORDER BY i.id } AS to
ORDER BY createdAt DESC
LIMIT $limit
