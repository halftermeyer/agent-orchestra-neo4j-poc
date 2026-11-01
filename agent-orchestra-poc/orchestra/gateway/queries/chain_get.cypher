CYPHER 25
MATCH (c:Chain {id: $chainId})
RETURN c.id AS id, c.status AS status, c.budget AS budget, c.spent AS spent, c.tokenBudget AS tokenBudget,
       c.tokensSpent AS tokensSpent, c.suspendReason AS suspendReason
