CYPHER 25
OPTIONAL MATCH (r:EntityRef {db: $db, key: $key})
OPTIONAL MATCH (r)-[:SAME_AS]->+(t:EntityRef) WHERE NOT EXISTS { (t)-[:SAME_AS]->() }
RETURN r IS NOT NULL AS known, r.deletedAt AS deletedAt, head(collect(t.key)) AS redirectTo
