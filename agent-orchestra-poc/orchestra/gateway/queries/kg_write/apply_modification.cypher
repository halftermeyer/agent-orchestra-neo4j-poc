CYPHER 25
MATCH (old:Part {id: $partId}), (new:Part {id: $replacementId})
WHERE old <> new AND old.retiredIn IS NULL AND new.retiredIn IS NULL
MATCH (prev:ProductVersion {current: true})
WITH old, new, prev, COUNT { MATCH (:ProductVersion) } AS n
SET prev.current = false, prev.supersededAt = toString(datetime())
CREATE (v:Entity:ProductVersion {id: 'VER-1.' + toString(n), label: 'v1.' + toString(n), current: true, releasedAt: toString(date()),
                                 reason: $reason, changeKey: $changeKey, partId: old.id, replacementId: new.id})
CREATE (v)-[:SUPERSEDES]->(prev)
SET old.retiredIn = v.id
CREATE (new)-[:IN_VERSION]->(v)
WITH old, new, v
MATCH (parent:Part)-[c:CONTAINS]->(old) WHERE c.removedIn IS NULL
SET c.removedIn = v.id
CREATE (parent)-[:CONTAINS {qty: c.qty, addedIn: v.id}]->(new)
RETURN v.id AS versionId, count(parent) AS parents
