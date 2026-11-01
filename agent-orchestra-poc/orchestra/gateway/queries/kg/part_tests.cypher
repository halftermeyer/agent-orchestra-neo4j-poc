CYPHER 25
MATCH (x:Part {id: $partId})
CALL (x) {
  MATCH (t:Test)-[:COVERS]->(x) RETURN t, true AS direct
  UNION
  MATCH ANY (x)<-[r:CONTAINS WHERE r.removedIn IS NULL]-+(a:Part)<-[:COVERS]-(t:Test) RETURN t, false AS direct
}
WITH t, collect(direct) AS ds
RETURN t.id AS id, t.name AS name, t.kind AS kind, t.durationDays AS durationDays, true IN ds AS direct
ORDER BY direct DESC, id
