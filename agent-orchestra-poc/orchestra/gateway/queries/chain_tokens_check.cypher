CYPHER 25
MERGE (c:Chain {id: $chainId})
  ON CREATE SET c.budget = $defaultBudget, c.spent = 0, c.tokenBudget = $defaultTokenBudget, c.tokensSpent = 0,
                c.status = 'active', c.createdAt = datetime(), c.createdBy = $agentId
RETURN c.status AS status, c.tokensSpent AS tokensSpent, c.tokenBudget AS tokenBudget
