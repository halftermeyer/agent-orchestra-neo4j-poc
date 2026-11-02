CYPHER 25
MATCH (p:Part {id: $key})
CALL (p) {
  MATCH path = ANY (p)<-[r:CONTAINS WHERE r.removedIn IS NULL]-+(a:Part)
  UNWIND relationships(path) AS e
  RETURN DISTINCT startNode(e) AS s, endNode(e) AS t, 'CONTAINS' AS type
  UNION
  MATCH (p)-[e:CONTAINS]->(c:Part) WHERE e.removedIn IS NULL
  RETURN p AS s, c AS t, 'CONTAINS' AS type
  UNION
  MATCH (x:Test)-[:COVERS]->(p)
  RETURN x AS s, p AS t, 'COVERS' AS type
}
RETURN s.id AS sid, s.name AS sname, labels(s) AS slabels, s.retiredIn AS sretired, t.id AS tid, t.name AS tname, labels(t) AS tlabels, t.retiredIn AS tretired, type
