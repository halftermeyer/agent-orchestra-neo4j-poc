CYPHER 25
MATCH (a:Agent {id: $agentId}), (to:Agent {id: $to}) WHERE a <> to
RETURN head(COLLECT { MATCH (a)-[:HAS_INBOX]->(i:Inbox) RETURN i.id }) AS debtorInbox,
       to:SoftwareAgent AND EXISTS { (to)-[:CAN_SEND_TO]->(:Inbox)<-[:HAS_INBOX]-(a) } AS creditorCanRemind,
       a:SoftwareAgent AS debtorIsSoftware
