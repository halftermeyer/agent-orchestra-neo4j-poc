CYPHER 25
MATCH (p:Part {id: $partId})<-[c:CONTAINS]-(parent:Part) WHERE c.removedIn IS NULL
WITH p, collect(parent.id) AS directParents
MATCH path = ANY (p)<-[r:CONTAINS WHERE r.removedIn IS NULL]-+(a:Part)
RETURN a.id AS id, a.name AS name, a.level AS level, a.id IN directParents AS direct, length(path) AS depth
ORDER BY level DESC, id
