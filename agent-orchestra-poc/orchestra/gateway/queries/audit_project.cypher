CYPHER 25
MATCH (aud:Agent {id: $agentId})-[:AUDITS]->(a:Agent)
MATCH (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(:Session)-[:SENT]->(m:Message)
WHERE m.createdAt > datetime() - duration({minutes: $window})
MATCH (m)<-[:RECEIVED]-(:InboxDay)<-[:HAS_DAY]-(:Inbox)<-[:HAS_INBOX]-(b:Agent) WHERE b <> a
WITH a, b, count(m) AS n
RETURN gds.graph.project($graphName, a, b, {relationshipProperties: {n: n}}) AS g
