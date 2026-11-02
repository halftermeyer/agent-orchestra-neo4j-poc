CYPHER 25
MATCH (p:Agent)-[v:VOTED]->(ap:Approval) WHERE v.at > datetime() - duration({hours: $hours})
RETURN p.id AS actor, v.decision AS decision, v.at AS at, ap.id AS approvalId, ap.status AS approvalStatus, v.onBehalfOf AS onBehalfOf
ORDER BY at DESC LIMIT 200
