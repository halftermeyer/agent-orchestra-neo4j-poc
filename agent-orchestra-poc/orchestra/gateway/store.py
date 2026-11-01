"""Seul module qui exécute du Cypher. Les requêtes sont figées dans queries/*.cypher et paramétrées."""
from pathlib import Path

from neo4j import GraphDatabase, unit_of_work
from neo4j.time import Date, DateTime, Duration, Time

QUERY_DIR = Path(__file__).parent / "queries"


class Queries:
    def __init__(self):
        self._q = {p.relative_to(QUERY_DIR).with_suffix("").as_posix(): p.read_text(encoding="utf-8")
                   for p in QUERY_DIR.rglob("*.cypher")}
        bad = [n for n, t in self._q.items() if not t.lstrip().startswith("CYPHER 25")]
        if bad:
            raise RuntimeError(f"requêtes sans 'CYPHER 25' : {bad}")

    def __getitem__(self, name: str) -> str:
        return self._q[name]

    def names(self):
        return list(self._q)


QUERIES = Queries()


class Runner:
    """Exécute des requêtes nommées dans une transaction."""

    def __init__(self, tx):
        self._tx = tx

    def all(self, name: str, **params) -> list[dict]:
        return self._tx.run(QUERIES[name], params).data()

    def one(self, name: str, **params) -> dict | None:
        rows = self.all(name, **params)
        return rows[0] if rows else None


class Store:
    def __init__(self, uri: str, user: str, password: str, db: str, kg_auth: tuple[str, str] | None = None):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.kg_driver = GraphDatabase.driver(uri, auth=kg_auth) if kg_auth else None   # conservateur de KG : écriture KG seule
        self.db = db

    def close(self):
        self.driver.close()
        if self.kg_driver:
            self.kg_driver.close()

    def write_kg(self, database: str, meta: dict, fn):
        """Écriture dans un KG, réservée aux effets d'outils approuvés (jamais exposée aux agents)."""
        @unit_of_work(metadata={k: str(v) for k, v in meta.items()})
        def work(tx):
            return fn(Runner(tx))
        with self.kg_driver.session(database=database) as s:
            return s.execute_write(work)

    def read(self, fn, database: str | None = None):
        with self.driver.session(database=database or self.db) as s:
            return s.execute_read(lambda tx: fn(Runner(tx)))

    def write(self, meta: dict, fn):
        """Écriture avec txMetadata (agentId, chainId) : règle 8."""
        @unit_of_work(metadata={k: str(v) for k, v in meta.items()})
        def work(tx):
            return fn(Runner(tx))
        with self.driver.session(database=self.db) as s:
            return s.execute_write(work)

    def run_in(self, database: str, name: str, **params) -> list[dict]:
        """Lecture d'un modèle sur une base de KG (nom de base issu du graphe, jamais du LLM)."""
        with self.driver.session(database=database, default_access_mode="READ") as s:
            return s.run(QUERIES[name], params).data()


def to_json(x):
    if isinstance(x, (DateTime,)):
        return x.to_native().isoformat()
    if isinstance(x, (Date, Time, Duration)):
        return str(x)
    if isinstance(x, dict):
        return {k: to_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_json(v) for v in x]
    return x
