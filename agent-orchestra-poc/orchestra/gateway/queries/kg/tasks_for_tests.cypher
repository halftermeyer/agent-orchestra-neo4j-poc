CYPHER 25
MATCH (t:Task) WHERE any(x IN t.testRefs WHERE x IN $testIds)
RETURN t.id AS id, t.name AS name, t.durationDays AS durationDays, t.plannedStartDay AS plannedStartDay
ORDER BY id
