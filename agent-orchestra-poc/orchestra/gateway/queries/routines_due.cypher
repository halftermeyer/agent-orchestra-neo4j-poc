CYPHER 25
MATCH (o:Agent)-[:OWNS]->(r:Routine {enabled: true})
WHERE (r.trigger = 'cron' AND (r.nextRunAt IS NULL OR r.nextRunAt <= datetime($now)))
   OR (r.trigger = 'once' AND r.firedAt IS NULL AND r.runAt <= datetime($now))
MATCH (r)-[:DELIVERS_TO]->(i:Inbox)
RETURN r.id AS id, r.trigger AS trigger, r.cron AS cron, r.tz AS tz, r.nextRunAt AS nextRunAt, r.runAt AS runAt,
       r.misfire AS misfire, r.payload AS payload, o.id AS owner, i.id AS deliverTo
ORDER BY r.id
