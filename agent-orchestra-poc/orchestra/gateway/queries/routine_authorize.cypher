CYPHER 25
MATCH (a:Agent {id: $agentId})
OPTIONAL MATCH (i:Inbox {id: $deliverTo})
OPTIONAL MATCH (t:Inbox:Topic {id: $listensTo})
RETURN i IS NOT NULL AND (EXISTS { (a)-[:HAS_INBOX]->(i) } OR EXISTS { (a)-[:CAN_SEND_TO]->(i) }) AS canDeliver,
       $listensTo IS NULL OR t IS NOT NULL AS topicOk
