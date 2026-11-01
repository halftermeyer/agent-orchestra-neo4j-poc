CYPHER 25
MATCH (a:Agent:SoftwareAgent {id: $actingAgent})
MATCH (i:Inbox {id: $inbox})
RETURN EXISTS { (a)-[:HAS_INBOX]->(i) } OR EXISTS { (a)-[:CAN_SEND_TO]->(i) } AS ok, coalesce(a.quarantined, false) AS quarantined
