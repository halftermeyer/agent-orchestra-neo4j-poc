CYPHER 25
MATCH (p:Part {id: $partId})
RETURN p.id AS id, p.name AS name, p.level AS level, p.family AS family, p.revision AS revision, p.criticality AS criticality,
       p.retiredIn AS retiredIn
