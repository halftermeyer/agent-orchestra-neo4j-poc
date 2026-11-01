CYPHER 25
MATCH (c:Commitment {id: $id, agentId: $agentId, status: 'open'})
SET c.status = 'fulfilled', c.fulfilledAt = datetime()
WITH c
CALL (c) {
  OPTIONAL MATCH (r:Routine {id: 'rt-commit-' + c.id}) WHERE r.firedAt IS NULL
  WITH r WHERE r IS NOT NULL
  SET r.enabled = false, r.disabledAt = datetime()
  RETURN count(*) AS cancelled
}
RETURN c.id AS id, c.fulfilledAt AS fulfilledAt
