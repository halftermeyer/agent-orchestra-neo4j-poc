CYPHER 25
MATCH (s:Session {id: $sessionId, agentId: $agentId})
MATCH (c:Chain {id: $chainId})
CREATE (m:Message {id: $messageId, from: $agentId, performative: $performative, conversationId: $conversationId,
                   chainId: $chainId, createdAt: datetime(), body: $body, inReplyTo: $inReplyTo, payloadJson: $payloadJson})
CREATE (s)-[:SENT]->(m)
CREATE (m)-[:IN_CHAIN]->(c)
WITH m
CALL (m) {
  OPTIONAL MATCH (src:Message {id: $derivedFrom})
  WITH m, src WHERE src IS NOT NULL
  CREATE (m)-[:DERIVED_FROM]->(src)
  RETURN count(*) AS derived
}
UNWIND $recipients AS rid
MATCH (i:Inbox {id: rid})
MERGE (d:Day:InboxDay {inboxId: i.id, date: date(m.createdAt)})
MERGE (i)-[:HAS_DAY]->(d)
CREATE (d)-[:RECEIVED {status: 'submitted', submittedAt: m.createdAt}]->(m)
RETURN DISTINCT m.id AS id, m.createdAt AS createdAt
