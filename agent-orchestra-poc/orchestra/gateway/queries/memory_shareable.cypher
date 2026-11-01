CYPHER 25
MATCH (me:Agent {id: $agentId}), (mem:Memory {id: $memoryId})
RETURN EXISTS { (me)-[:HAS_MEMORY]->(mem) } OR EXISTS { (me)-[:CAN_SHARE]->(mem) } AS ok
