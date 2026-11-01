CYPHER 25
MATCH (c:Chain {id: $chainId})
SET c.tokensSpent = c.tokensSpent + $tokens
WITH c, c.status AS prev, c.tokensSpent >= c.tokenBudget AS over
SET c.status = CASE WHEN prev = 'active' AND over THEN 'suspended' ELSE c.status END,
    c.suspendedAt = CASE WHEN prev = 'active' AND over THEN datetime() ELSE c.suspendedAt END,
    c.suspendReason = CASE WHEN prev = 'active' AND over THEN 'tokens' ELSE c.suspendReason END
RETURN c.status AS status, c.tokensSpent AS tokensSpent, c.tokenBudget AS tokenBudget
