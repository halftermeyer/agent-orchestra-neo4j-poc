CYPHER 25
MATCH (t:Task)
RETURN t.id AS id, t.name AS name, t.phase AS phase, t.durationDays AS durationDays, t.plannedStartDay AS plannedStartDay,
       t.testRefs AS testRefs, t.partRef AS partRef,
       COLLECT { MATCH (t)-[:DEPENDS_ON]->(d:Task) RETURN d.id } AS dependsOn
ORDER BY id
