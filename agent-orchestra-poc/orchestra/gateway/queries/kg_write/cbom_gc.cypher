CYPHER 25
// 5.4 of the configurable-bom page (verbatim, plus the final RETURN)
// Remove  RESOLVED_LINKs not connected to Product
MATCH ()<-[r:RESOLVED_LINK {id_variant: $id_variant}]-(x)
WHERE NOT EXISTS {(x)<-[:RESOLVED_LINK {id_variant: $id_variant}]-*(:Product)}
DELETE r
RETURN count(*) AS deleted
