CYPHER 25
MERGE (c:Chain {id: $chainId})
  ON CREATE SET c.spent = 0, c.tokensSpent = 0, c.status = 'active', c.createdAt = datetime(), c.createdBy = $by
SET c.budget = $budget, c.tokenBudget = $tokenBudget, c.stopCriterion = $stopCriterion, c.maxTurns = $maxTurns
RETURN c.id AS id, c.status AS status, c.budget AS budget, c.tokenBudget AS tokenBudget
