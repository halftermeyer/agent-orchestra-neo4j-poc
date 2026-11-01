CYPHER 25
MATCH (a:Agent {id: $agentId})-[cu:CAN_USE]->(t:Tool {name: $tool})
RETURN t.effect AS effect, cu.approval AS approval
