CYPHER 25
MERGE (c:Chain {id: $chainId})
  ON CREATE SET c.budget = $defaultBudget, c.spent = 0, c.tokenBudget = $defaultTokenBudget, c.tokensSpent = 0,
                c.status = 'active', c.createdAt = datetime(), c.createdBy = $agentId
WITH c, c.status AS prev, (c.status = 'active' AND c.spent + $n <= c.budget) AS ok
SET c.spent = CASE WHEN ok THEN c.spent + $n ELSE c.spent END
WITH c, prev, ok
SET c.status = CASE WHEN prev = 'active' AND NOT ok THEN 'suspended' ELSE c.status END,
    c.suspendedAt = CASE WHEN prev = 'active' AND NOT ok THEN datetime() ELSE c.suspendedAt END,
    c.suspendReason = CASE WHEN prev = 'active' AND NOT ok THEN 'budget' ELSE c.suspendReason END
RETURN ok, prev, c.status AS status, c.spent AS spent, c.budget AS budget
