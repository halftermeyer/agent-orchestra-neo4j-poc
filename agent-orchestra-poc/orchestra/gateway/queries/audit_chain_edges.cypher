CYPHER 25
MATCH (aud:Agent {id: $agentId})-[:AUDITS]->(a:Agent)
MATCH (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(:Session)-[:SENT]->(m:Message)
WHERE m.createdAt > datetime() - duration({minutes: $window})
MATCH (m)-[:IN_CHAIN]->(c:Chain {status: 'active'})
MATCH (m)<-[:RECEIVED]-(:InboxDay)<-[:HAS_DAY]-(:Inbox)<-[:HAS_INBOX]-(b:Agent) WHERE b <> a
RETURN c.id AS chainId, a.id AS from, b.id AS to, count(m) AS n, min(m.createdAt) AS first, max(m.createdAt) AS last,
       c.budget AS budget, c.spent AS spent, c.tokenBudget AS tokenBudget, c.tokensSpent AS tokensSpent,
       c.maxTurns AS maxTurns, c.stopCriterion AS stopCriterion
