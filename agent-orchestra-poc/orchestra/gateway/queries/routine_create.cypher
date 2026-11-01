CYPHER 25
MATCH (a:Agent {id: $agentId}), (i:Inbox {id: $deliverTo})
CREATE (r:Routine {id: $id, trigger: $trigger, cron: $cron, tz: $tz, runAt: CASE WHEN $runAt IS NULL THEN null ELSE datetime($runAt) END,
                   payload: $payload, filter: $filter, enabled: true, misfire: $misfire, createdAt: datetime()})
CREATE (a)-[:OWNS]->(r)
CREATE (r)-[:DELIVERS_TO]->(i)
WITH r
CALL (r) {
  OPTIONAL MATCH (t:Inbox:Topic {id: $listensTo})
  WITH r, t WHERE t IS NOT NULL
  CREATE (r)-[:LISTENS_TO]->(t)
  RETURN count(*) AS listens
}
RETURN r.id AS id, r.trigger AS trigger, r.enabled AS enabled
