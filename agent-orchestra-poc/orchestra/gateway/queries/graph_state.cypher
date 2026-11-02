CYPHER 25
MATCH (a:Agent)
RETURN a.id AS id,
       EXISTS { (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(s:Session) WHERE s.closedAt IS NULL } AS busy,
       head(COLLECT { MATCH (a)-[:HAS_WORKSPACE]->(:Workspace)-[:HAS_DAY]->(:WorkDay)-[:OPENED]->(:Session)-[:STATUS]->(u:StatusUpdate)
                      RETURN {text: u.text, at: u.at} ORDER BY u.at DESC LIMIT 1 }) AS lastStatus,
       COUNT { (a)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED {status: 'submitted'}]->(:Message) } AS pending,
       COUNT { (a)-[:COMMITTED]->(:Commitment {status: 'open'}) } AS commitments,
       COUNT { (a)-[:HAS_INBOX]->(:Inbox)-[:HAS_DAY]->(:InboxDay)-[:RECEIVED {status: 'input-required'}]->(:Message) } AS inputRequired,
       COUNT { (a)-[:HAS_MEMORY]->(:Memory)-[:ASSERTS]->(:Fact) } AS facts
ORDER BY id
