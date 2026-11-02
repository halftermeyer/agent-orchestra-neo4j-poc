CYPHER 25
CALL () {
  MATCH (a:Agent)
  RETURN collect({id: a.id, name: coalesce(a.name, a.id), person: a:Person, role: a.role, title: a.title,
                  quarantined: coalesce(a.quarantined, false),
                  kind: head([(a)-[:CURRENT]->(v:AgentVersion) | v.kind]), model: head([(a)-[:CURRENT]->(v:AgentVersion) | v.model]),
                  inbox: head([(a)-[:HAS_INBOX]->(i:Inbox) | i.id])}) AS agents
}
CALL () { MATCH (i:Inbox) RETURN collect({id: i.id, topic: i:Topic}) AS inboxes }
CALL () { MATCH (a:Agent)-[:SUPERVISES]->(b:Agent) RETURN collect({from: a.id, to: b.id}) AS supervises }
CALL () { MATCH (a:Agent)-[:CAN_SEND_TO]->(i:Inbox) RETURN collect({from: a.id, to: i.id}) AS canSendTo }
CALL () { MATCH (a:Agent)-[:AUDITS]->(b:Agent) RETURN collect({from: a.id, to: b.id}) AS audits }
CALL () { MATCH (a:Agent)-[:CAN_QUERY]->(k:KnowledgeGraph) RETURN collect({from: a.id, to: k.id}) AS canQuery }
CALL () { MATCH (k:KnowledgeGraph) RETURN collect({id: k.id, dbName: k.dbName}) AS kgs }
CALL () {
  MATCH (o:Agent)-[:OWNS]->(r:Routine)
  OPTIONAL MATCH (r)-[:DELIVERS_TO]->(d:Inbox)
  OPTIONAL MATCH (r)-[:LISTENS_TO]->(t:Inbox)
  RETURN collect({id: r.id, owner: o.id, trigger: r.trigger, cron: r.cron, enabled: r.enabled, nextRunAt: r.nextRunAt,
                  runAt: r.runAt, deliversTo: d.id, listensTo: t.id}) AS routines
}
RETURN agents, inboxes, supervises, canSendTo, audits, canQuery, kgs, routines
