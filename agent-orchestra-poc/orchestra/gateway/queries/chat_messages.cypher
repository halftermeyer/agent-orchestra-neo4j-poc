CYPHER 25
MATCH (me:Agent {id: $agentId})
CALL (me) {
  MATCH (me)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m:Message) RETURN m, 'in' AS direction
  UNION
  MATCH (m:Message {from: me.id}) RETURN m, 'out' AS direction
}
WITH m, min(direction) AS direction
RETURN m.id AS id, m.from AS from, m.performative AS performative, m.body AS body, m.payloadJson AS payloadJson,
       m.chainId AS chainId, m.createdAt AS createdAt, direction,
       COLLECT { MATCH (i:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED]->(m) RETURN i.id ORDER BY i.id } AS to,
       EXISTS { (m)-[g:CAN_READ]->(:Memory) WHERE g.until > datetime() } AS hasSharedMemory
ORDER BY createdAt DESC
LIMIT $limit
