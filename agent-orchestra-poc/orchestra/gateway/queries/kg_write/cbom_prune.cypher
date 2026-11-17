CYPHER 25
// 5.3 of the configurable-bom page, verbatim except the tie-break on the option id (deterministic, mirrored by the
// Python oracle) and the final RETURN.
// Converge before 10 iterations unless height of ConfigGroups tree is > 10
UNWIND range(1, 10) AS _
CALL (_) {

// Find unresolved ConfigGroups with no unresolved ConfigGroups underneath
MATCH (cf:ConfigGroup)
WHERE count{(cf)-[:RESOLVED_LINK {id_variant: $id_variant}]->()} > 1
AND NOT EXISTS {
  (cf)-[:RESOLVED_LINK {id_variant: $id_variant}]->+(cf_below:ConfigGroup)
  WHERE count{(cf_below)-[:RESOLVED_LINK {id_variant: $id_variant}]->()} > 1
}
RETURN cf

NEXT

// Compute costs and weight for all options of a given ConfigGroup
MATCH path = (leaf)<-[rs:RESOLVED_LINK {id_variant: $id_variant}]-*(opt)
    <-[opt_link:RESOLVED_LINK {id_variant: $id_variant}]-(cf)
WHERE NOT EXISTS {(leaf)-[:RESOLVED_LINK {id_variant: $id_variant}]->()}
WITH cf, opt_link, opt, leaf, reduce(acc=1,r IN rs | acc * coalesce(r.qty, 1)) AS times
WITH cf, opt_link, opt, leaf, {cost: leaf.cost * times, weight: leaf.weight * times} AS vals
WITH cf, opt_link, opt, collect(vals) AS vals_list
WITH cf, opt_link, opt, reduce (acc= {cost: 0.0, weight:0.0}, vals In vals_list|
    {cost: acc.cost + vals.cost, weight: acc.weight + vals.weight}) AS vals

// Apply scoring strategy set as parameter to select the best option
UNWIND $scoring AS field_factor
WITH cf, opt_link, opt, vals[field_factor.field] * field_factor.factor AS score
WITH cf, opt_link, opt, sum (score) AS score
ORDER BY cf, score DESC, opt.id

// Detach unselected branch
WITH cf, collect(opt_link) AS opt_links
UNWIND opt_links[1..] AS del_opt_link
DELETE del_opt_link

}
RETURN count(*) AS iterations
