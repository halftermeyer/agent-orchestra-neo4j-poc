CYPHER 25
MATCH (a:Agent {id: $agentId})
RETURN a.id AS id, coalesce(a.name, a.id) AS name, a:Person AS person, a.role AS role, a.title AS title, coalesce(a.quarantined, false) AS quarantined,
       head(COLLECT { MATCH (a)-[:CURRENT]->(v:AgentVersion) RETURN {id: v.id, kind: v.kind, model: v.model, prompt: v.prompt, createdAt: v.createdAt} }) AS version,
       COLLECT { MATCH (a)-[:CURRENT]->(:AgentVersion)-[:SUPERSEDES]->*(v) RETURN v.id ORDER BY v.id } AS versionHistory,
       head(COLLECT { MATCH (a)-[:HAS_MANDATE]->(m:Mandate) RETURN {purpose: m.purpose, scope: m.scope, successCriteria: m.successCriteria} }) AS mandate,
       COLLECT { MATCH (a)-[c:CAN_USE]->(t:Tool) RETURN {name: t.name, effect: t.effect, approval: c.approval} ORDER BY t.name } AS tools,
       COLLECT { MATCH (a)-[:CAN_QUERY]->(k:KnowledgeGraph) RETURN k.id } AS kgs,
       COLLECT { MATCH (s:Agent)-[:SUPERVISES]->(a) RETURN s.id } AS supervisors,
       COLLECT { MATCH (a)-[:SUPERVISES]->(b:Agent) RETURN b.id } AS subordinates,
       COLLECT { MATCH (a)-[:AUDITS]->(b:Agent) RETURN b.id } AS audits,
       COLLECT { MATCH (a)-[:OWNS]->(r:Routine) RETURN {id: r.id, trigger: r.trigger, cron: r.cron, enabled: r.enabled} ORDER BY r.id } AS routines,
       COLLECT { MATCH (a)-[:COMMITTED]->(c:Commitment {status: 'open'}) RETURN {id: c.id, to: c.toAgent, description: c.description, dueAt: c.dueAt} ORDER BY c.dueAt } AS commitments,
       COUNT { (a)-[:HAS_MEMORY]->(:Memory)-[:ASSERTS]->(:Fact) } AS facts,
       COLLECT { MATCH (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(:Session)-[:STATUS]->(u:StatusUpdate)
                 RETURN {text: u.text, at: u.at} ORDER BY u.at DESC LIMIT 5 } AS statuses,
       COLLECT { MATCH (tc:ToolCall {agentId: a.id})-[:OF]->(t:Tool) RETURN {tool: t.name, status: tc.status, at: tc.startedAt} ORDER BY tc.startedAt DESC LIMIT 8 } AS toolCalls
