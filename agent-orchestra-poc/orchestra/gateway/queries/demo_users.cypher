CYPHER 25
MATCH (p:Agent:Person)
RETURN p.id AS id, coalesce(p.name, p.id) AS name, p.title AS title
ORDER BY id
