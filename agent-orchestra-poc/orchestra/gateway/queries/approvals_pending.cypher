CYPHER 25
MATCH (me:Agent:Person {id: $agentId})
MATCH (ap:Approval {status: 'pending'})-[:FOR]->(tc:ToolCall)
WHERE (EXISTS { (me)-[:HAS_INBOX]->(:Inbox {id: ap.electorate}) }
       OR EXISTS { (me)-[d:ACTS_FOR]->(:Agent:Person)-[:HAS_INBOX]->(:Inbox {id: ap.electorate}) WHERE d.until > datetime() })
  AND NOT EXISTS { (me)-[:VOTED]->(ap) }
RETURN ap.id AS id, ap.policy AS policy, ap.quorum AS quorum, ap.size AS size, ap.requestedBy AS requestedBy,
       ap.requestedAt AS requestedAt, tc.args AS args,
       COUNT { (:Agent)-[:VOTED]->(ap) } AS votes,
       head(COLLECT { MATCH (tc)<-[:CALLED]-(s:Session) RETURN s.chainId }) AS chainId
ORDER BY requestedAt
