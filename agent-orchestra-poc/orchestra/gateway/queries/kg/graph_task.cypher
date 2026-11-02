CYPHER 25
MATCH (k:Task {id: $key})
CALL (k) {
  MATCH (k)-[:DEPENDS_ON]->(d:Task) RETURN k AS s, d AS t, 'DEPENDS_ON' AS type
  UNION
  MATCH (u:Task)-[:DEPENDS_ON]->(k) RETURN u AS s, k AS t, 'DEPENDS_ON' AS type
  UNION
  MATCH (k)-[:ASSIGNED_TO]->(r:Resource) RETURN k AS s, r AS t, 'ASSIGNED_TO' AS type
}
RETURN s.id AS sid, s.name AS sname, labels(s) AS slabels, null AS sretired, t.id AS tid, t.name AS tname, labels(t) AS tlabels, null AS tretired, type
