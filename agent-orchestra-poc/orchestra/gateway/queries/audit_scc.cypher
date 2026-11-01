CYPHER 25
CALL gds.scc.stream($graphName) YIELD nodeId, componentId
WITH componentId, collect(gds.util.asNode(nodeId).id) AS agents
WHERE size(agents) > 1
RETURN componentId, agents
