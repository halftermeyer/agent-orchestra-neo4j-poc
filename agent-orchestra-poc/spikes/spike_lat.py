import time, threading, random, statistics, warnings, logging
logging.getLogger("neo4j").setLevel(logging.ERROR)
from neo4j import GraphDatabase
D = GraphDatabase.driver("bolt://localhost:17687", auth=("neo4j", "orchestra-dev-pw"))
def run(q, **p):
    try:
        with D.session(database="orchestra") as s: return [r.data() for r in s.run(q, **p)]
    except Exception as e: return f"ERR {str(e)[:250]}"

print("== vector index with filter property (WITH [memoryId])")
run("DROP INDEX fact_emb IF EXISTS")
print(run("CYPHER 25 CREATE VECTOR INDEX fact_emb2 IF NOT EXISTS FOR (f:Fact) ON (f.embedding) WITH [f.memoryId] OPTIONS {indexConfig:{`vector.dimensions`:3,`vector.similarity_function`:'cosine'}}"))
run("CALL db.awaitIndexes(60)")
print(run("CYPHER 25 MATCH (f:Fact) SEARCH f IN (VECTOR INDEX fact_emb2 FOR [50.0,1.0,0.5] WHERE f.memoryId = 'm1' LIMIT 10) SCORE AS s RETURN count(*) AS n, collect(f.id)[..5] AS ids"))
print(run("CYPHER 25 MATCH (f:Fact) SEARCH f IN (VECTOR INDEX fact_emb2 FOR [50.0,1.0,0.5] WHERE f.memoryId IN ['m1','m2'] LIMIT 10) SCORE AS s RETURN count(*) AS n"))

print("== CDC latency, decoupled writer/poller")
for poll_ms in (100, 250, 500):
    cur = run("CALL db.cdc.current() YIELD id RETURN id")[0]["id"]
    committed = {}; seen = {}; stop = False
    def writer():
        for i in range(30):
            mid = f"L{poll_ms}-{i}"
            time.sleep(random.uniform(0.05, 0.4))
            run("CREATE (:Message {id:$id})", id=mid)
            committed[mid] = time.perf_counter()
    w = threading.Thread(target=writer); w.start()
    while w.is_alive() or len(seen) < 30:
        rows = run("CALL db.cdc.query($c, [{select:'n', labels:['Message']}]) YIELD id, event RETURN id, event.state.after.properties.id AS mid", c=cur)
        now = time.perf_counter()
        for r in rows:
            cur = r["id"]; seen.setdefault(r["mid"], now)
        time.sleep(poll_ms/1000)
        if time.perf_counter() - min(committed.values(), default=now) > 60: break
    lat = sorted((seen[m]-committed[m])*1000 for m in committed if m in seen)
    print(f"poll={poll_ms}ms n={len(lat)} mean={statistics.mean(lat):.0f}ms p50={lat[len(lat)//2]:.0f} p95={lat[int(len(lat)*.95)-1]:.0f} max={lat[-1]:.0f}")
