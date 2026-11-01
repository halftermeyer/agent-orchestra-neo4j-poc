CYPHER 25
MATCH ACYCLIC (me:Agent {id: $agentId})-[:SUPERVISES]->*(a:Agent)
CALL (me, a) {
  MATCH (a)-[:HAS_MEMORY]->(m:Memory)
  WHERE a = me OR NOT a:Person
  RETURN m, datetime() AS asOf
  UNION
  MATCH (a)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false))
  RETURN m, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf
  UNION
  MATCH (a)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(:Message)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false)) AND (a = me OR NOT a:Person)
  RETURN m, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf
}
WITH m, max(asOf) AS asOf
RETURN collect({id: m.id, asOf: asOf}) AS scopes
