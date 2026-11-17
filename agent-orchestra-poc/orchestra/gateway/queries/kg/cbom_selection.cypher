CYPHER 25
// Released configuration of the CBOM: for every ConfigGroup, the option(s) currently mounted at its position
// (live configurable CONTAINS carrying the group id). These become the allow_list constraints of the baseline variant.
MATCH (prod:Product)
MATCH (g:ConfigGroup)
OPTIONAL MATCH (:Part)-[c:CONTAINS {group: g.id}]->(sel:Part) WHERE c.removedIn IS NULL
WITH prod, g, collect(DISTINCT sel.id) AS selected
RETURN prod.id AS productId, g.id AS group, g.category AS category, selected
ORDER BY group
