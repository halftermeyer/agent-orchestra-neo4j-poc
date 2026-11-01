CYPHER 25
MATCH (a:Agent {id: $agentId})
RETURN a.id AS id, a.name AS name, a.role AS role, labels(a) AS labels,
  head(COLLECT { MATCH (a)-[:CURRENT]->(v:AgentVersion) RETURN {id: v.id, kind: v.kind, model: v.model, prompt: v.prompt, toolset: v.toolset} }) AS version,
  head(COLLECT { MATCH (a)-[:HAS_MANDATE]->(m:Mandate) RETURN {purpose: m.purpose, scope: m.scope, successCriteria: m.successCriteria} }) AS mandate,
  COLLECT { MATCH (a)-[c:CAN_USE]->(t:Tool) RETURN {name: t.name, effect: t.effect, approval: c.approval} } AS tools,
  COLLECT { MATCH (a)-[:CAN_SEND_TO]->(i:Inbox) RETURN i.id } AS canSendTo,
  COLLECT { MATCH (a)-[:CAN_QUERY]->(k:KnowledgeGraph) RETURN k.id } AS kgs,
  COLLECT { MATCH (a)-[:HAS_INBOX]->(i:Inbox) RETURN i.id } AS inboxes
