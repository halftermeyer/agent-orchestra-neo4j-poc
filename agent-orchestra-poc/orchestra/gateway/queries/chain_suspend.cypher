CYPHER 25
MATCH (aud:Agent {id: $agentId, role: 'auditor'})-[:CAN_USE]->(:Tool {name: 'suspend_chain'})
MATCH (c:Chain {id: $chainId})
WITH aud, c, c.status AS prev
SET c.status = 'suspended',
    c.suspendedAt = CASE WHEN prev = 'suspended' THEN c.suspendedAt ELSE datetime() END,
    c.suspendReason = CASE WHEN prev = 'suspended' THEN c.suspendReason ELSE 'audit' END
MERGE (aud)-[s:SUSPENDED {chainId: c.id}]->(c)
  ON CREATE SET s.reason = $reason, s.at = datetime()
RETURN c.status AS status
