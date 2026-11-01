CYPHER 25
MATCH (ap:Approval {id: $approvalId}) WHERE ap.status = 'pending'
MATCH (p:Agent:Person {id: $personId})
WHERE NOT EXISTS { MATCH (:Agent)-[v:VOTED]->(ap) WHERE coalesce(v.onBehalfOf, v.personId) = $effectiveVoter }
CREATE (p)-[v:VOTED {approvalId: ap.id, personId: p.id, decision: $decision, at: datetime(), comment: $comment, onBehalfOf: $onBehalfOf}]->(ap)
RETURN v.at AS at
