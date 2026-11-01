CYPHER 25
MATCH (r:Routine {enabled: true, trigger: 'event'})-[:LISTENS_TO]->(:Inbox:Topic {id: $topicId})
MATCH (o:Agent)-[:OWNS]->(r)
MATCH (r)-[:DELIVERS_TO]->(i:Inbox)
RETURN r.id AS id, r.filter AS filter, o.id AS owner, i.id AS deliverTo, r.payload AS payload
ORDER BY r.id
