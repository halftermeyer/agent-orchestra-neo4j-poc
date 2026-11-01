CYPHER 25
MATCH (c:Chain {id: $chainId}) WHERE c.status = 'suspended'
SET c.status = 'active', c.resumedAt = datetime(), c.resumedBy = $by,
    c.budget = c.budget + $extraBudget, c.tokenBudget = c.tokenBudget + $extraTokens
RETURN c.status AS status, c.budget AS budget
