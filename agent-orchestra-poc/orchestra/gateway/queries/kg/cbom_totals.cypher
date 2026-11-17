CYPHER 25
// 5.5 of the configurable-bom page (verbatim, plus the leaf count)
// Compute weight and cost of resolved BOM
MATCH path = (leaf)<-[rs:RESOLVED_LINK {id_variant: $id_variant}]-*(:Product)
WHERE NOT EXISTS {(leaf)-[:RESOLVED_LINK {id_variant: $id_variant}]->()}
WITH leaf, reduce(acc=1,r IN rs | acc * coalesce(r.qty, 1)) AS times
WITH leaf, {cost: leaf.cost * times, weight: leaf.weight * times} AS vals
WITH collect(vals) AS vals_list
WITH reduce (acc= {cost: 0.0, weight:0.0}, vals In vals_list| {cost: acc.cost + vals.cost, weight: acc.weight + vals.weight}) AS vals,
     size(vals_list) AS leafPaths
RETURN vals.weight AS weight, vals.cost AS cost, leafPaths
