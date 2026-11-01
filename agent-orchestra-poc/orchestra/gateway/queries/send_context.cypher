CYPHER 25
MATCH (me:Agent {id: $agentId})
RETURN me:Person AS isPerson,
       EXISTS { (me)-[:HAS_MANDATE]->(:Mandate) } AS hasMandate,
       COLLECT { MATCH (s:Agent)-[:SUPERVISES]->(me), (s)-[:HAS_INBOX]->(i:Inbox) RETURN i.id } AS supervisorInboxes,
       COLLECT { UNWIND $recipients AS rid MATCH (me)-[:CAN_SEND_TO]->(i:Inbox {id: rid}) RETURN i.id } AS allowed
