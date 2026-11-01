CYPHER 25
MATCH (a:Agent {id: $agentId})-[:CAN_QUERY]->(k:KnowledgeGraph)
WHERE k.id IN $kgIds OR k.dbName IN $kgIds
RETURN k.id AS id, k.dbName AS dbName
