import re
from pathlib import Path

import orchestra.gateway.app  # noqa: F401  (loads all routes)
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.store import QUERIES

GATEWAY = Path(__file__).resolve().parents[1] / "orchestra" / "gateway"


def test_all_queries_are_cypher25_files():
    assert len(QUERIES.names()) > 40
    assert all(QUERIES[n].lstrip().startswith("CYPHER 25") for n in QUERIES.names())


def test_only_the_store_executes_cypher():
    """No Cypher built elsewhere: only store.py calls `.run(`; no Cypher f-string."""
    for f in GATEWAY.rglob("*.py"):
        src = f.read_text()
        if f.name != "store.py":
            assert not re.search(r"\.run\(", src.replace("r.one(", "").replace("r.all(", "")), f"{f} runs Cypher"
        assert "MATCH (" not in src or f.name == "store.py", f"{f} contains inline Cypher"


def test_no_agent_facing_request_model_accepts_an_agent_identity():
    """Rule 3. Only the templates of the `internal` module (sys token of the CDC consumer) name the acting agent."""
    def models(c):
        for s in c.__subclasses__():
            yield s
            yield from models(s)
    agent_facing = [m for m in models(Strict) if not m.__module__.endswith("routes.internal")]
    names = {n for m in agent_facing for n in m.model_fields}
    assert not names & {"agentId", "agent_id", "from", "sender", "actingAgent"}, names
