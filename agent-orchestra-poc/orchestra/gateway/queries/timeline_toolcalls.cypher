CYPHER 25
MATCH (tc:ToolCall)-[:OF]->(t:Tool) WHERE tc.startedAt > datetime() - duration({hours: $hours})
RETURN tc.agentId AS actor, t.name AS tool, tc.status AS status, tc.startedAt AS at, tc.endedAt AS endedAt
ORDER BY at DESC LIMIT 300
