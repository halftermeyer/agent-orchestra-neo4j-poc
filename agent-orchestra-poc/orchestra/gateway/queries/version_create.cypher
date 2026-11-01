CYPHER 25
MATCH (a:Agent:SoftwareAgent {id: $agentId})-[c:CURRENT]->(old:AgentVersion)
CALL (a) { MATCH (a)-[:CURRENT]->(:AgentVersion)-[:SUPERSEDES]->*(v) RETURN count(v) AS n }
CREATE (v:AgentVersion {id: a.id + '@v' + toString(n + 1), kind: old.kind, prompt: coalesce($prompt, old.prompt),
                        model: coalesce($model, old.model), toolset: old.toolset, createdAt: datetime(), createdBy: $by})
CREATE (v)-[:SUPERSEDES]->(old)
DELETE c
CREATE (a)-[:CURRENT]->(v)
RETURN v.id AS id, old.id AS supersedes
