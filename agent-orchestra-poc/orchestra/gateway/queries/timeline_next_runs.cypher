CYPHER 25
MATCH (o:Agent)-[:OWNS]->(r:Routine {enabled: true}) WHERE r.nextRunAt IS NOT NULL OR (r.trigger = 'once' AND r.firedAt IS NULL)
RETURN r.id AS routine, o.id AS actor, r.trigger AS trigger, coalesce(r.nextRunAt, r.runAt) AS at
ORDER BY at LIMIT 50
