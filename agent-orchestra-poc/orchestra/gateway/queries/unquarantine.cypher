CYPHER 25
MATCH (a:Agent:SoftwareAgent {id: $target}) WHERE a.quarantined = true
SET a.quarantined = false, a.releasedAt = datetime(), a.releasedBy = $by
RETURN a.id AS id
