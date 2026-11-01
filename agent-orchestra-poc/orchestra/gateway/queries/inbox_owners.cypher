CYPHER 25
OPTIONAL MATCH (i:Inbox {id: $inboxId})
RETURN i IS NOT NULL AS exists, coalesce(i:Topic, false) AS topic,
       COLLECT { MATCH (a:Agent)-[:HAS_INBOX]->(i) RETURN {id: a.id, person: a:Person, quarantined: coalesce(a.quarantined, false)} ORDER BY a.id } AS owners
