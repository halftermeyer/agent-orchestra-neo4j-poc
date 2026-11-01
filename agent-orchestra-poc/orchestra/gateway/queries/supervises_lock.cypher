CYPHER 25
MATCH (a:Agent {id: $from}), (b:Agent {id: $to})
CALL apoc.lock.nodes([a, b])
RETURN a = b AS self,
       EXISTS { MATCH ANY (b)-[:SUPERVISES]->*(a) } AS cycle,
       (a:SoftwareAgent AND b:Person) AS softwareOverPerson
