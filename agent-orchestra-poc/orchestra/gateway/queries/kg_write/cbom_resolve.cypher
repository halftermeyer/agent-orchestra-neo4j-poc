CYPHER 25
// 5.1 of the configurable-bom page (field-industry-use-cases). Deviations (docs/spikes.md):
// the product is chosen by id; the traversal follows the BOM types only (CONTAINS = the page's HAS_PART), skips
// removed links (removedIn) and configurable CONTAINS (their position is a ConfigGroup); in the PoC every BOM node is
// a Part, so a leaf is a Part that is neither the Product nor an Assembly.
MATCH path = (p:Product {id: $product_id})((x)-[r:CONTAINS|REQUIRES|HAS_OPTION]->(y)
WHERE r.removedIn IS NULL AND r.configurable IS NULL
AND NOT (
    x:ConfigGroup
    AND any (cons IN $constraints WHERE (
      cons.category = x.category
      AND any (prop IN cons.properties WHERE
        (
          NOT prop.allow_list IS null
          AND NOT y[prop.name] IN prop.allow_list
        )
        OR (
          NOT prop.deny_list IS null
          AND y[prop.name] IN prop.deny_list
        )
        )
      )
    )
  )
)*(last:Part&!Product&!Assembly)
UNWIND relationships(path) AS rel
RETURN startNode(rel) AS source, rel AS r, endNode(rel) AS target

NEXT

MERGE (source)-[rl:RESOLVED_LINK {id_variant: $id_variant, rel_type: type(r)}]->(target)
SET rl.qty = r.qty
RETURN count(*) AS links
