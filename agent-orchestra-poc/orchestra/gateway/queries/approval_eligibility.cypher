CYPHER 25
MATCH (p:Agent:Person {id: $personId}), (ap:Approval {id: $approvalId})
RETURN EXISTS { (p)-[:HAS_INBOX]->(:Inbox {id: ap.electorate}) } AS member,
       head(COLLECT {
         MATCH (p)-[d:ACTS_FOR]->(m:Agent:Person)-[:HAS_INBOX]->(:Inbox {id: ap.electorate})
         WHERE d.until > datetime()
         RETURN m.id ORDER BY m.id
       }) AS delegatorId
