CYPHER 25
MATCH (m:Message {id: $messageId})
RETURN m.id AS id, m.from AS from, m.chainId AS chainId, m.createdAt AS createdAt
