import re
from pathlib import Path

import orchestra.gateway.app  # noqa: F401  (charge toutes les routes)
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.store import QUERIES

GATEWAY = Path(__file__).resolve().parents[1] / "orchestra" / "gateway"


def test_all_queries_are_cypher25_files():
    assert len(QUERIES.names()) > 40
    assert all(QUERIES[n].lstrip().startswith("CYPHER 25") for n in QUERIES.names())


def test_only_the_store_executes_cypher():
    """Aucun Cypher construit ailleurs : seul store.py appelle `.run(` ; pas de f-string Cypher."""
    for f in GATEWAY.rglob("*.py"):
        src = f.read_text()
        if f.name != "store.py":
            assert not re.search(r"\.run\(", src.replace("r.one(", "").replace("r.all(", "")), f"{f} exécute du Cypher"
        assert "MATCH (" not in src or f.name == "store.py", f"{f} contient du Cypher en ligne"


def test_no_agent_facing_request_model_accepts_an_agent_identity():
    """Règle 3. Seuls les modèles du module `internal` (jeton sys du consommateur CDC) nomment l'agent d'agissement."""
    def models(c):
        for s in c.__subclasses__():
            yield s
            yield from models(s)
    agent_facing = [m for m in models(Strict) if not m.__module__.endswith("routes.internal")]
    names = {n for m in agent_facing for n in m.model_fields}
    assert not names & {"agentId", "agent_id", "from", "sender", "actingAgent"}, names
