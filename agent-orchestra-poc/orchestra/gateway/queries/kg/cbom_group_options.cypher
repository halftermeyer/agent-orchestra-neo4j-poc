CYPHER 25
// The 150% view of some ConfigGroups: every option they offer
MATCH (g:ConfigGroup)-[:HAS_OPTION]->(o)
WHERE g.id IN $groups
RETURN g.id AS group, o.id AS option
ORDER BY group, option
