CYPHER 25
MATCH (p:Part {id: $partId})-[c:CONTAINS]->(x:Part) WHERE c.removedIn IS NULL
RETURN x.id AS id, x.name AS name, x.level AS level, c.qty AS qty
ORDER BY id
