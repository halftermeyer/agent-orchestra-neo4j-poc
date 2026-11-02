import json
import re
import time
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase
from starlette.testclient import TestClient

from orchestra import config
from orchestra.gateway.app import create_app
from orchestra.gateway.auth import make_token
from orchestra.gateway.llm.base import GenResult, LLMProvider, ToolCallRequest, Usage
from orchestra.gateway.settings import Settings
from orchestra.seed.load import load_orchestra

ROOT = Path(__file__).resolve().parents[1]
TESTDB = "orchestratest"
MASTER = "test-master-key"
DYNAMIC = ["Message", "Session", "StatusUpdate", "Fact", "EntityRef", "ToolCall", "Approval", "Chain", "AccessLog", "InboxDay", "WorkDay", "Commitment", "Run"]


@pytest.fixture(scope="session")
def admin():
    with GraphDatabase.driver(config.NEO4J_URI, auth=(config.ADMIN_USER, config.ADMIN_PASSWORD)) as d:
        yield d


@pytest.fixture
def q(admin):
    def run(db, query, **p):
        with admin.session(database=db) as s:
            return [r.data() for r in s.run("CYPHER 25\n" + query, **p)]
    return run


def _statements(path: Path):
    text = "\n".join(l for l in path.read_text().splitlines() if not l.strip().startswith("//"))
    for st in text.split(";"):
        st = re.sub(r"^\s*CYPHER 25\s*", "", st).strip()
        if st:
            yield "CYPHER 25\n" + st


@pytest.fixture(scope="session")
def testdb(admin):
    with admin.session(database="system") as s:
        s.run(f"DROP DATABASE {TESTDB} IF EXISTS WAIT").consume()
        s.run(f"CREATE DATABASE {TESTDB} WAIT").consume()
        s.run(f"ALTER DATABASE {TESTDB} SET OPTION txLogEnrichment 'FULL'").consume()
        for g in (f"GRANT ACCESS ON DATABASE {TESTDB} TO gateway_rw", f"GRANT MATCH {{*}} ON GRAPH {TESTDB} TO gateway_rw",
                  f"GRANT WRITE ON GRAPH {TESTDB} TO gateway_rw", f"GRANT NAME MANAGEMENT ON DATABASE {TESTDB} TO gateway_rw",
                  f"GRANT ACCESS ON DATABASE {TESTDB} TO cdc_reader"):
            s.run(g).consume()
    for _ in range(60):
        try:
            with admin.session(database=TESTDB) as s:
                s.run("CALL db.cdc.current() YIELD id RETURN id").consume()
            break
        except Exception:
            time.sleep(1)
    with admin.session(database=TESTDB) as s:
        for st in _statements(ROOT / "db" / "schema.cypher"):
            s.run(st).consume()
        s.run("CALL db.awaitIndexes(60)").consume()
    load_orchestra(admin, TESTDB)
    yield TESTDB
    with admin.session(database="system") as s:
        s.run(f"DROP DATABASE {TESTDB} IF EXISTS").consume()


@pytest.fixture
def tq(q, testdb):
    return lambda query, **p: q(testdb, query, **p)


@pytest.fixture(autouse=True)
def _clean(request):
    if "testdb" not in request.fixturenames and "client" not in request.fixturenames:
        yield
        return
    tq = request.getfixturevalue("tq")
    yield
    tq("MATCH (n) WHERE n.test = true OR any(l IN labels(n) WHERE l IN $labels) DETACH DELETE n", labels=DYNAMIC)
    tq("MATCH (a:Agent) WHERE a.quarantined IS NOT NULL SET a.quarantined = false")
    tq("MATCH (r:Routine) WHERE r.createdAt IS NOT NULL DETACH DELETE r")       # routines created by the API (the seed has no createdAt)


class FakeLLM(LLMProvider):
    def __init__(self):
        self.usage = Usage(10, 5)
        self.calls = []
        self.next_tool_calls = []
        self.script = []          # scripted turns: {"tools": [(name, args)]} or {"text": "..."}
        self.history = []         # (system, contents) of each call

    def generate(self, *, model, system, contents, tools=None):
        self.calls.append({"model": model, "system": system, "tools": [t["name"] for t in tools or []]})
        self.history.append((system, [dict(c) for c in contents]))
        if self.script:
            step = self.script.pop(0)
            calls = [ToolCallRequest(n, a) for n, a in step.get("tools", [])]
            return GenResult(None if calls else step.get("text", "ok"), calls, self.usage)
        calls = [ToolCallRequest(n, a) for n, a in self.next_tool_calls]
        return GenResult(None if calls else "ok", calls, self.usage)

    def embed(self, texts, dim):
        out = []
        for t in texts:
            v = [0.0] * dim
            for w in re.findall(r"\w+", t.lower()):
                v[hash(w) % dim] += 1.0
            out.append(v)
        return out

    def count_tokens(self, model, contents):
        return sum(len(c.get("text") or "") for c in contents) // 4

    def list_models(self):
        return ["fake-model-a", "fake-model-b"]


@pytest.fixture(scope="session")
def fake():
    return FakeLLM()


@pytest.fixture(scope="session")
def client(testdb, fake, tmp_path_factory):
    st = Settings(db=testdb, master_key=MASTER, data_dir=tmp_path_factory.mktemp("gw"), neo4j_uri=config.NEO4J_URI,
                  neo4j_password=config.GATEWAY_PASSWORD, kg_password=config.KGCURATOR_PASSWORD, demo_login=True,
                  recordings_dir=str(tmp_path_factory.mktemp("rec")))
    app = create_app(st, llm_factory=lambda key: fake)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.ctx = app.state.ctx
        yield c


def tok(kind, ident="admin"):
    return {"Authorization": "Bearer " + make_token(MASTER, kind, ident)}


@pytest.fixture
def world(client, tq, fake):
    """Factory of test agents (property test=true, deleted after each test)."""
    fake.usage = Usage(10, 5)
    fake.next_tool_calls = []
    fake.script = []
    fake.calls.clear()
    fake.history.clear()
    client.ctx.keystore.set("test-key-0000")

    class W:
        c = client

        def agent(self, id, *, person=False, mandate=True, tools=(), inbox=None, kgs=()):
            lab = "Person" if person else "SoftwareAgent"
            tq(f"""CREATE (a:Agent:{lab} {{id: $id, test: true, name: $id}})
                   MERGE (i:Inbox {{id: $inbox}}) ON CREATE SET i.test = true
                   CREATE (a)-[:HAS_INBOX]->(i)
                   CREATE (a)-[:HAS_WORKSPACE]->(:Workspace {{id: 'ws:' + $id, test: true}})
                   CREATE (a)-[:HAS_MEMORY]->(:Memory {{id: 'mem:' + $id, ownerId: $id, test: true}})""",
               id=id, inbox=inbox or f"inbox:{id}")
            if not person:
                tq("""MATCH (a:Agent {id: $id}) CREATE (a)-[:CURRENT]->(:AgentVersion {id: $id + '@v1', kind: 'llm', model: 'fake-model', test: true})""", id=id)
            if mandate and not person:
                tq("MATCH (a:Agent {id: $id}) CREATE (a)-[:HAS_MANDATE]->(:Mandate {id: 'mandate:' + $id, purpose: 't', test: true})", id=id)
            for t in tools:
                name, appr = (t, "none") if isinstance(t, str) else t
                tq("MATCH (a:Agent {id: $id}), (t:Tool {name: $t}) CREATE (a)-[:CAN_USE {approval: $ap}]->(t)", id=id, t=name, ap=appr)
            for k in kgs:
                tq("MATCH (a:Agent {id: $id}), (k:KnowledgeGraph {id: $k}) CREATE (a)-[:CAN_QUERY {mode: 'read'}]->(k)", id=id, k=k)
            return id

        def send_to(self, a, *inboxes):
            for i in inboxes:
                tq("MATCH (a:Agent {id: $a}), (i:Inbox {id: $i}) MERGE (a)-[:CAN_SEND_TO]->(i)", a=a, i=i)

        def supervises(self, boss, sub):
            tq("MATCH (a:Agent {id: $a}), (b:Agent {id: $b}) CREATE (a)-[:SUPERVISES {since: datetime()}]->(b)", a=boss, b=sub)

        def trigger(self, agent, chain=None, payload=None, body="x", sender="admin", performative="inform"):
            """Drops a message into the agent's inbox (as the router would)."""
            mid = uuid.uuid4().hex
            tq("""MATCH (a:Agent {id: $a})-[:HAS_INBOX]->(i:Inbox)
                  MERGE (d:Day:InboxDay {inboxId: i.id, date: date()}) MERGE (i)-[:HAS_DAY]->(d)
                  MERGE (c:Chain {id: $chain}) ON CREATE SET c.budget = 50, c.spent = 0, c.tokenBudget = 200000, c.tokensSpent = 0, c.status = 'active', c.createdAt = datetime()
                  CREATE (m:Message {id: $m, from: $sender, performative: $perf, chainId: $chain, createdAt: datetime(), body: $body, payloadJson: $pj})
                  CREATE (m)-[:IN_CHAIN]->(c)
                  CREATE (d)-[:RECEIVED {status: 'submitted', submittedAt: datetime()}]->(m)""",
               a=agent, m=mid, chain=chain or uuid.uuid4().hex, sender=sender, perf=performative, body=body,
               pj=json.dumps(payload) if payload is not None else None)
            return mid

        def session(self, agent, chain=None):
            mid = self.trigger(agent, chain)
            r = client.post("/sessions", json={"messageId": mid}, headers=tok("svc", agent))
            assert r.status_code == 200, r.text
            return r.json()["id"]

        def post(self, path, agent, body, kind="svc"):
            return client.post(path, json=body, headers=tok(kind, agent))

        def remember(self, agent, sid, text, **kw):
            r = self.post("/facts", agent, {"sessionId": sid, "statement": text, **kw})
            assert r.status_code == 201, r.text
            return r.json()["id"]

        def recall(self, agent, query, kind="svc", **kw):
            r = self.post("/recall", agent, {"query": query, **kw}, kind=kind)
            assert r.status_code == 200, r.text
            return {f["statement"] for f in r.json()["facts"]}

        def send(self, agent, sid, to, body="hi", perf="inform", **kw):
            return self.post("/messages", agent, {"to": to, "performative": perf, "body": body, "sessionId": sid, **kw})

    yield W()
    client.ctx.keystore.delete()


# ---------- phase 3 : consommateur CDC ----------
import socket
import threading

import httpx
import uvicorn
from neo4j import unit_of_work

from orchestra.cdc.consumer import Consumer
from orchestra.cdc.cursors import CursorStore
from orchestra.cdc.gateway_client import GatewayClient
from orchestra.cdc.hub import Hub
from orchestra.cdc.scheduler import Scheduler
from orchestra.cdc.settings import CdcSettings
from orchestra.cdc.source import CdcSource

KGTEST = "kgtest"


@pytest.fixture(scope="session")
def gw_url(testdb, fake, tmp_path_factory):
    """Real HTTP gateway (the consumer writes only through it)."""
    st = Settings(db=testdb, master_key=MASTER, data_dir=tmp_path_factory.mktemp("gw-live"), neo4j_uri=config.NEO4J_URI,
                  neo4j_password=config.GATEWAY_PASSWORD, env_llm_key="test-key-0000", kg_password=config.KGCURATOR_PASSWORD)
    app = create_app(st, llm_factory=lambda key: fake)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(timeout=5)


@pytest.fixture(scope="session")
def kgtest(admin):
    with admin.session(database="system") as s:
        s.run(f"DROP DATABASE {KGTEST} IF EXISTS WAIT").consume()
        s.run(f"CREATE DATABASE {KGTEST} WAIT").consume()
        s.run(f"ALTER DATABASE {KGTEST} SET OPTION txLogEnrichment 'FULL'").consume()
        s.run(f"GRANT ACCESS ON DATABASE {KGTEST} TO cdc_reader").consume()
        for g in (f"GRANT ACCESS ON DATABASE {KGTEST} TO gateway_rw", f"GRANT MATCH {{*}} ON GRAPH {KGTEST} TO gateway_rw",
                  f"GRANT ACCESS ON DATABASE {KGTEST} TO kg_curator", f"GRANT MATCH {{*}} ON GRAPH {KGTEST} TO kg_curator",
                  f"GRANT WRITE ON GRAPH {KGTEST} TO kg_curator", f"GRANT NAME MANAGEMENT ON DATABASE {KGTEST} TO kg_curator"):
            s.run(g).consume()
    for _ in range(60):
        try:
            with admin.session(database=KGTEST) as s:
                s.run("CALL db.cdc.current() YIELD id RETURN id").consume()
            break
        except Exception:
            time.sleep(1)
    with admin.session(database=KGTEST) as s:
        for st in _statements(ROOT / "db" / "schema_kg.cypher"):
            s.run(st).consume()
    yield KGTEST
    with admin.session(database="system") as s:
        s.run(f"DROP DATABASE {KGTEST} IF EXISTS").consume()


class CdcEnv:
    def __init__(self, settings, consumer, scheduler, hub, gw):
        self.settings, self.consumer, self.scheduler, self.hub, self.gw = settings, consumer, scheduler, hub, gw
        self.events, self.wakes = [], []
        hub.on_event(self.events.append)
        hub.on_wake(lambda a, i: self.wakes.append((a, i)))

    def drain(self, settle: float = 0.4, timeout: float = 15.0) -> int:
        """Processes until quiescence. An event is only readable in the CDC a moment after the commit:
        so keep polling for at least `settle` seconds, then until two empty polls."""
        total, quiet, start = 0, 0, time.monotonic()
        while time.monotonic() - start < timeout:
            n = self.consumer.poll_once()
            total += n
            quiet = quiet + 1 if n == 0 else 0
            if quiet >= 2 and time.monotonic() - start >= settle:
                break
            if n == 0:
                time.sleep(0.05)
        return total

    def of(self, type_, **match):
        return [e for e in self.events if e["type"] == type_ and all(e.get(k) == v or e["payload"].get(k) == v for k, v in match.items())]


@pytest.fixture
def cdc(testdb, kgtest, gw_url, tmp_path):
    st = CdcSettings(neo4j_uri=config.NEO4J_URI, neo4j_user=config.CDC_USER, neo4j_password=config.CDC_PASSWORD,
                     orchestra_db=testdb, kg_dbs={KGTEST: "produit"}, bridge_dbs=(KGTEST,), gateway_url=gw_url,
                     sys_token=make_token(MASTER, "sys", "cdc"), data_dir=tmp_path, owners_ttl=0.0)
    gw = GatewayClient(gw_url, st.sys_token)
    hub = Hub()
    consumer = Consumer(st, CdcSource(st.neo4j_uri, st.neo4j_user, st.neo4j_password), gw, CursorStore(tmp_path / "cursors.json"), hub)
    time.sleep(0.4)       # events from the previous test are only readable a moment after their commit
    consumer.init_cursors()
    env = CdcEnv(st, consumer, Scheduler(st, gw, hub), hub, gw)
    yield env
    consumer.source.close()


# ---------- phase 4 ----------
@pytest.fixture
def kg_world(world, tq, admin, kgtest):
    """The "produit" KG points at the test database; a minimal BOM is created there."""
    tq("MATCH (k:KnowledgeGraph {id: 'produit'}) SET k.dbName = $kgdb", kgdb=KGTEST)
    with admin.session(database=KGTEST) as s:
        s.run("""CYPHER 25 MATCH (n) DETACH DELETE n""").consume()
        s.run("""CYPHER 25 CREATE (v:Entity:ProductVersion {id: 'VER-1.0', label: 'v1.0', current: true}),
                 (prod:Entity:Part {id: 'P0', name: 'Produit', level: 0}), (asm:Entity:Part {id: 'A1', name: 'Ensemble', level: 2}),
                 (old:Entity:Part {id: 'X1', name: 'Faulty part', level: 3, family: 'F'}), (new:Entity:Part {id: 'X2', name: 'New part', level: 3, family: 'F'}),
                 (prod)-[:CONTAINS {qty: 1}]->(asm), (asm)-[:CONTAINS {qty: 4}]->(old)""").consume()
    yield world
    tq("MATCH (k:KnowledgeGraph {id: 'produit'}) SET k.dbName = 'kgproduit'")
    with admin.session(database=KGTEST) as s:
        s.run("CYPHER 25 MATCH (n) DETACH DELETE n").consume()


