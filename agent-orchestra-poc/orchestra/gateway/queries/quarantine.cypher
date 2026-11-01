CYPHER 25
MATCH (aud:Agent {id: $agentId, role: 'auditor'})-[:CAN_USE]->(:Tool {name: 'quarantine_agent'})
MATCH (a:Agent:SoftwareAgent {id: $target}) WHERE a <> aud
SET a.quarantined = true, a.quarantinedAt = coalesce(a.quarantinedAt, datetime())
MERGE (aud)-[q:QUARANTINED {targetId: a.id}]->(a)
  ON CREATE SET q.reason = $reason, q.at = datetime()
RETURN a.id AS id
