CYPHER 25
MATCH (old:EntityRef {db: $db, key: $key}) WHERE $key <> $target
MERGE (new:Ref:EntityRef {db: $db, key: $target})
  ON CREATE SET new.label = coalesce($label, old.label), new.labelAt = datetime()
MERGE (old)-[s:SAME_AS]->(new) ON CREATE SET s.at = datetime()
SET old.redirectedAt = coalesce(old.redirectedAt, datetime())
WITH old, new
MATCH (old)-[:IN_KG]->(k:KnowledgeGraph)
MERGE (new)-[:IN_KG]->(k)
RETURN new.key AS key
