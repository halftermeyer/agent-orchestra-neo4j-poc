CYPHER 25
MATCH (o:Agent)-[:OWNS]->(r:Routine {id: $id}) WHERE o.id = $agentId OR $isAdmin
SET r.enabled = false, r.disabledAt = coalesce(r.disabledAt, datetime())
RETURN r.id AS id
