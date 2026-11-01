CYPHER 25
MATCH (c:Chain {id: $chainId})
MATCH (i:Inbox {id: $inbox})
CREATE (m:Message {id: $messageId, from: $from, performative: $performative, conversationId: $conversationId,
                   chainId: $chainId, createdAt: datetime(), body: $body, payloadJson: $payloadJson,
                   system: true, actingAgent: $actingAgent})
CREATE (m)-[:IN_CHAIN]->(c)
WITH m, i
CALL (m) {
  OPTIONAL MATCH (e:Message {id: $aboutEvent})
  WITH m, e WHERE e IS NOT NULL
  CREATE (m)-[:ABOUT_EVENT]->(e)
  RETURN count(*) AS about
}
MERGE (d:Day:InboxDay {inboxId: i.id, date: date(m.createdAt)})
MERGE (i)-[:HAS_DAY]->(d)
CREATE (d)-[:RECEIVED {status: 'submitted', submittedAt: m.createdAt}]->(m)
RETURN m.id AS id, m.createdAt AS createdAt
