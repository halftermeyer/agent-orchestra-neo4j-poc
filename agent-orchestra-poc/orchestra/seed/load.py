"""Chargement idempotent (MERGE) des seeds. Requêtes statiques et paramétrées."""
import json
from pathlib import Path

from neo4j import GraphDatabase

from orchestra import config
from orchestra.seed import kg_data as K
from orchestra.seed import orchestra_data as O

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _run(session, q, **p):
    session.run("CYPHER 25\n" + q, **p).consume()


def load_orchestra(drv, db="orchestra"):
    persons = [{**p, "oidcSub": f"demo|{p['id']}"} for p in O.PERSONS]
    agents = [{k: a[k] for k in ("id", "name", "kind", "role")} | {"workloadId": f"orchestra-runtime-{a['id']}"} for a in O.AGENTS]
    with drv.session(database=db) as s:
        _run(s, "UNWIND $rows AS r MERGE (a:Agent:Person {id: r.id}) SET a.name = r.name, a.title = r.title, a.oidcSub = r.oidcSub", rows=persons)
        _run(s, """UNWIND $rows AS r MERGE (a:Agent:SoftwareAgent {id: r.id})
                   SET a.name = r.name, a.role = r.role, a.workloadId = r.workloadId""", rows=agents)
        # inbox / workspace / mémoire (3 racines distinctes)
        ids = [a["id"] for a in O.AGENTS] + [p["id"] for p in O.PERSONS]
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.id})
                   MERGE (i:Inbox {id: r.inbox}) MERGE (a)-[:HAS_INBOX]->(i)
                   MERGE (w:Workspace {id: 'ws:' + r.id}) MERGE (a)-[:HAS_WORKSPACE]->(w)
                   MERGE (m:Memory {id: 'mem:' + r.id}) SET m.ownerId = r.id MERGE (a)-[:HAS_MEMORY]->(m)""",
             rows=[{"id": i, "inbox": O.INBOX_OF[i]} for i in ids])
        _run(s, "UNWIND $rows AS r MERGE (t:Inbox:Topic {id: r.id}) SET t.retention = r.retention", rows=O.TOPICS)
        # mandats et versions (une version initiale ; on ne réécrit jamais une version existante)
        agent_rows = [{k: a[k] for k in ("id", "kind", "prompt", "purpose", "scope", "success", "tools")} for a in O.AGENTS]
        _run(s, """UNWIND $rows AS r MATCH (a:Agent:SoftwareAgent {id: r.id})
                   MERGE (m:Mandate {id: 'mandate:' + r.id})
                   ON CREATE SET m.purpose = r.purpose, m.scope = r.scope, m.successCriteria = r.success, m.authoredBy = 'admin', m.createdAt = datetime()
                   MERGE (a)-[:HAS_MANDATE]->(m)""", rows=agent_rows)
        _run(s, """UNWIND $rows AS r MATCH (a:Agent:SoftwareAgent {id: r.id}) WHERE NOT EXISTS { (a)-[:CURRENT]->(:AgentVersion) }
                   MERGE (v:AgentVersion {id: r.id + '@v1'})
                   ON CREATE SET v.kind = r.kind, v.prompt = r.prompt, v.model = CASE r.kind WHEN 'llm' THEN $model END,
                                 v.toolset = r.tools, v.createdAt = datetime()
                   MERGE (a)-[:CURRENT]->(v)""", rows=agent_rows, model=O.MODEL)
        # un prompt modifié dans le seed = une nouvelle AgentVersion (SUPERSEDES), jamais une réécriture
        _run(s, """UNWIND $rows AS r MATCH (a:Agent:SoftwareAgent {id: r.id})-[c:CURRENT]->(old:AgentVersion)
                   WHERE old.prompt <> r.prompt
                   CALL (a) { MATCH (a)-[:CURRENT]->(:AgentVersion)-[:SUPERSEDES]->*(v) RETURN count(v) AS n }
                   CREATE (v:AgentVersion {id: a.id + '@v' + toString(n + 1), kind: old.kind, prompt: r.prompt, model: old.model,
                                           toolset: r.tools, createdAt: datetime(), createdBy: 'seed'})
                   CREATE (v)-[:SUPERSEDES]->(old)
                   DELETE c
                   CREATE (a)-[:CURRENT]->(v)""",
             rows=[{k: a[k] for k in ("id", "prompt", "tools")} for a in O.AGENTS])
        _run(s, "UNWIND $rows AS r MERGE (t:Tool {name: r.name}) SET t.effect = r.effect", rows=O.TOOLS)
        can_use = [{"agent": a["id"], "tool": t, "approval": "none"} for a in O.AGENTS for t in a["tools"]]
        can_use += [{"agent": a, "tool": t, "approval": ap} for a, t, ap in O.EXTRA_CAN_USE]
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.agent}), (t:Tool {name: r.tool})
                   MERGE (a)-[c:CAN_USE]->(t) SET c.approval = r.approval""", rows=can_use)
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.from}), (b:Agent {id: r.to})
                   MERGE (a)-[x:SUPERVISES]->(b) ON CREATE SET x.since = datetime()""",
             rows=[{"from": a, "to": b} for a, b in O.SUPERVISES])
        _run(s, """UNWIND $ids AS id MATCH (aud:Agent {id: 'auditeur'}), (b:Agent {id: id}) MERGE (aud)-[:AUDITS]->(b)""", ids=O.AUDITS)
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.agent}), (i:Inbox {id: r.inbox}) MERGE (a)-[:CAN_SEND_TO]->(i)""",
             rows=[{"agent": a, "inbox": i} for a, lst in O.CAN_SEND_TO.items() for i in lst])
        _run(s, "UNWIND $rows AS r MERGE (k:KnowledgeGraph {id: r.id}) SET k.dbName = r.dbName", rows=O.KGS)
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.agent}), (k:KnowledgeGraph {id: r.kg})
                   MERGE (a)-[q:CAN_QUERY]->(k) SET q.mode = 'read'""",
             rows=[{"agent": a, "kg": k} for a, lst in O.CAN_QUERY.items() for k in lst])
        routines = [{"id": r["id"], "owner": r["owner"], "trigger": r["trigger"], "to": r["to"], "listens": r.get("listens"),
                     "filter": r.get("filter"), "cron": r.get("cron"), "tz": r.get("tz"), "payload": r.get("payload")} for r in O.ROUTINES]
        _run(s, """UNWIND $rows AS r MATCH (a:Agent {id: r.owner}), (i:Inbox {id: r.to})
                   MERGE (rt:Routine {id: r.id})
                   SET rt.trigger = r.trigger, rt.cron = r.cron, rt.tz = r.tz, rt.payload = r.payload,
                       rt.filter = r.filter, rt.enabled = true, rt.misfire = 'skip'
                   MERGE (a)-[:OWNS]->(rt) MERGE (rt)-[:DELIVERS_TO]->(i)
                   WITH rt, r WHERE r.listens IS NOT NULL
                   MATCH (t:Inbox:Topic {id: r.listens}) MERGE (rt)-[:LISTENS_TO]->(t)""", rows=routines)


def load_kg_produit(drv, d):
    with drv.session(database="kgproduit") as s:
        _run(s, "UNWIND $rows AS r MERGE (e:Entity:Part {id: r.id}) ON CREATE SET e += r", rows=d["parts"])
        _run(s, "UNWIND $rows AS r MERGE (e:Entity:Test {id: r.id}) ON CREATE SET e += r", rows=d["tests"])
        _run(s, "UNWIND $rows AS r MERGE (e:Entity:ProductVersion {id: r.id}) ON CREATE SET e += r", rows=d["versions"])
        _run(s, """UNWIND $rows AS r MATCH (a:Part {id: r.from}), (b:Part {id: r.to})
                   MERGE (a)-[x:CONTAINS]->(b) ON CREATE SET x.qty = r.qty""", rows=d["contains"])
        _run(s, """UNWIND $rows AS r MATCH (a:Test {id: r.from}), (b:Part {id: r.to}) MERGE (a)-[:COVERS]->(b)""", rows=d["covers"])
        _run(s, """MATCH (v:ProductVersion {id: 'VER-1.0'}), (p:Part) WHERE NOT EXISTS { (p)-[:IN_VERSION]->(:ProductVersion) } MERGE (p)-[:IN_VERSION]->(v)""")


def load_kg_projet(drv, d):
    with drv.session(database="kgprojet") as s:
        _run(s, "UNWIND $rows AS r MERGE (e:Entity:Task {id: r.id}) ON CREATE SET e += r", rows=d["tasks"])
        _run(s, "UNWIND $rows AS r MERGE (e:Entity:Resource {id: r.id}) ON CREATE SET e += r", rows=d["resources"])
        _run(s, "UNWIND $rows AS r MATCH (a:Task {id: r.from}), (b:Task {id: r.to}) MERGE (a)-[:DEPENDS_ON]->(b)", rows=d["depends"])
        _run(s, "UNWIND $rows AS r MATCH (a:Task {id: r.from}), (b:Resource {id: r.to}) MERGE (a)-[:ASSIGNED_TO]->(b)", rows=d["assigned"])


def run_all():
    produit = K.generate_kg_produit()
    projet = K.generate_kg_projet(produit["tests"], [p["id"] for p in produit["parts"] if p["level"] == 1])
    incidents = K.generate_incidents(produit)
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "incidents.json").write_text(json.dumps(incidents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.ADMIN_USER, config.ADMIN_PASSWORD)) as drv:
        load_orchestra(drv)
        load_kg_produit(drv, produit)
        load_kg_projet(drv, projet)
    print(f"seed OK: {len(produit['parts'])} parts, {len(produit['tests'])} tests, {len(projet['tasks'])} tasks, {len(incidents)} incidents")
