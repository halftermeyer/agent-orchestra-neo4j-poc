CYPHER 25
MATCH (m:Message) WHERE m.from STARTS WITH 'routine:' AND m.createdAt > datetime() - duration({hours: $hours})
RETURN m.from AS routine, m.actingAgent AS actor, m.createdAt AS at, m.id AS messageId
ORDER BY at DESC LIMIT 200
