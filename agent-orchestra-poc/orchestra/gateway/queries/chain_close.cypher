CYPHER 25
MATCH (c:Chain {id: $chainId}) WHERE c.status IN ['active', 'suspended']
SET c.status = 'closed', c.closedAt = datetime(), c.closedBy = $by, c.closeReason = $reason
RETURN c.status AS status, c.closedAt AS closedAt
