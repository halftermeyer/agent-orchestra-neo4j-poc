CYPHER 25
MATCH sup = ACYCLIC (me:Agent {id: $agentId})-[:SUPERVISES]->*(a:Agent)
WITH me, a, [n IN nodes(sup) | n.id] AS chain, size(relationships(sup)) AS hops
CALL (me, a) {
  MATCH (a)-[:HAS_MEMORY]->(m:Memory) WHERE a = me OR NOT a:Person
  RETURN m.id AS memoryId, m.ownerId AS ownerId, datetime() AS asOf, [] AS via, ['HAS_MEMORY'] AS rels, 'memory' AS kind
  UNION
  MATCH (a)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false))
  RETURN m.id AS memoryId, m.ownerId AS ownerId, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf, [] AS via, ['CAN_READ'] AS rels, 'share' AS kind
  UNION
  MATCH (a)-[:HAS_INBOX]->(i:Inbox)-[:HAS_DAY]->(d:InboxDay)-[:RECEIVED]->(msg:Message)-[g:CAN_READ]->(m:Memory)
  WHERE g.until > datetime() AND (a = me OR NOT coalesce(g.private, false)) AND (a = me OR NOT a:Person)
  RETURN m.id AS memoryId, m.ownerId AS ownerId, CASE g.mode WHEN 'live' THEN datetime() ELSE g.asOf END AS asOf,
         [i.id, i.id + '@' + toString(d.date), msg.id] AS via, ['HAS_INBOX', 'HAS_DAY', 'RECEIVED', 'CAN_READ'] AS rels, 'message' AS kind
}
RETURN memoryId, ownerId, asOf, chain, via, rels, kind, hops
