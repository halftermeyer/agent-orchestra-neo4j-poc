CYPHER 25
MATCH (c:Commitment {id: $id})
RETURN c.id AS id, c.agentId AS agentId, c.status AS status
