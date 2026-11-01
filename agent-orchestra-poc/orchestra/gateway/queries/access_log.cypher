CYPHER 25
CREATE (l:AccessLog {id: $id, at: datetime(), agentId: $agentId, kind: $kind, granted: $granted,
                     targets: $targets, count: $count, detail: $detail})
RETURN l.id AS id
