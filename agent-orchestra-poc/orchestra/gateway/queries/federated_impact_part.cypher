CYPHER 25
CALL () {
  USE graph.byName('fed.kgproduit')
  MATCH (t:Test)-[:COVERS]->(:Part {id: $partId})
  RETURN collect(t.id) AS testIds
}
CALL (testIds) {
  USE graph.byName('fed.kgprojet')
  MATCH (k:Task) WHERE any(x IN k.testRefs WHERE x IN testIds)
  RETURN collect({id: k.id, name: k.name, durationDays: k.durationDays}) AS tasks
}
RETURN testIds, tasks
