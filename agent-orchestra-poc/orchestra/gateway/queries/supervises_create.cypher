CYPHER 25
MATCH (a:Agent {id: $from}), (b:Agent {id: $to})
MERGE (a)-[x:SUPERVISES]->(b) ON CREATE SET x.since = datetime()
RETURN x.since AS since
