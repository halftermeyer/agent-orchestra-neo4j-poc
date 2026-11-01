import time, statistics, sys
from neo4j import GraphDatabase
D = GraphDatabase.driver("bolt://localhost:17687", auth=("neo4j", "orchestra-dev-pw"))
def run(db, q, **p):
    try:
        with D.session(database=db) as s:
            return [r.data() for r in s.run(q, **p)]
    except Exception as e:
        return f"ERR {type(e).__name__}: {str(e)[:300]}"

print("== composite / byName")
run("kgproduit", "CYPHER 25 MATCH (n) DETACH DELETE n"); run("kgprojet", "CYPHER 25 MATCH (n) DETACH DELETE n")
run("kgproduit", "CREATE (:Entity {id:'P1'})"); run("kgprojet", "CREATE (:Entity {id:'T1'})")
print(run("fed", "CYPHER 25 UNWIND ['kgproduit','kgprojet'] AS g CALL (g) { USE graph.byName('fed.' + g) MATCH (e:Entity) RETURN e.id AS id } RETURN g, id"))
print(run("fed", "CYPHER 25 USE fed.kgproduit MATCH (e:Entity) RETURN e.id"))
print(run("fed", "CYPHER 25 WITH 'fed.kgprojet' AS n CALL (n) { USE graph.byName(n) MATCH (e:Entity) RETURN e.id AS id } RETURN id"))

print("== vector")
run("orchestra", "CYPHER 25 MATCH (n:Fact) DETACH DELETE n")
print(run("orchestra", "CREATE VECTOR INDEX fact_emb IF NOT EXISTS FOR (f:Fact) ON (f.embedding) OPTIONS {indexConfig:{`vector.dimensions`:3,`vector.similarity_function`:'cosine'}}"))
run("orchestra", "CALL db.awaitIndexes(30)")
run("orchestra", "UNWIND range(1,50) AS i CREATE (:Fact {id:i, memoryId: CASE WHEN i%2=0 THEN 'm1' ELSE 'm2' END, embedding:[toFloat(i),1.0,0.5]})")
print("post-filter:", run("orchestra", "CYPHER 25 CALL db.index.vector.queryNodes('fact_emb', 10, [50.0,1.0,0.5]) YIELD node, score WHERE node.memoryId='m1' RETURN count(*) AS n"))
print("SEARCH w/ WHERE:", run("orchestra", "CYPHER 25 MATCH (f:Fact) SEARCH f IN (VECTOR INDEX fact_emb FOR [50.0,1.0,0.5] WHERE f.memoryId = 'm1' LIMIT 10) SCORE AS s RETURN count(*) AS n, collect(f.id)[..5] AS ids"))
print("SEARCH w/o WHERE:", run("orchestra", "CYPHER 25 MATCH (f:Fact) SEARCH f IN (VECTOR INDEX fact_emb FOR [50.0,1.0,0.5] LIMIT 10) SCORE AS s RETURN count(*) AS n"))

print("== apoc.util.validate")
print(run("orchestra", "CYPHER 25 CREATE (x:Probe {id:99}) WITH x CALL apoc.util.validate(true, 'budget exceeded %d', [5]) RETURN x"))
print("probe 99 persisted?", run("orchestra", "MATCH (x:Probe {id:99}) RETURN count(x) AS n"))
print(run("orchestra", "CYPHER 25 CREATE (x:Probe {id:98}) WITH x CALL apoc.util.validate(false, 'nope', []) RETURN x.id"))

print("== CDC latency (write -> visible in db.cdc.query)")
cur = run("orchestra", "CALL db.cdc.current() YIELD id RETURN id")[0]["id"]
for poll_ms in (100, 250, 500):
    lat = []
    for i in range(20):
        mid = f"lat-{poll_ms}-{i}"
        t0 = time.perf_counter()
        run("orchestra", "CREATE (:Message {id:$id})", id=mid)
        found = False
        while not found:
            rows = run("orchestra", "CALL db.cdc.query($c, [{select:'n', labels:['Message']}]) YIELD id, event RETURN id, event.state.after.properties.id AS mid", c=cur)
            for r in rows:
                cur = r["id"]
                if r["mid"] == mid: found = True
            if not found: time.sleep(poll_ms/1000)
        lat.append((time.perf_counter()-t0)*1000)
    lat.sort()
    print(f"poll={poll_ms}ms n=20 mean={statistics.mean(lat):.0f}ms p50={lat[10]:.0f} p95={lat[18]:.0f} max={lat[-1]:.0f}")
