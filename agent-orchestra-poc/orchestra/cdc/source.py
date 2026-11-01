from neo4j import GraphDatabase

from orchestra.gateway.store import to_json


class CdcSource:
    """Lecture du CDC avec l'utilisateur `cdc` (ACCESS + EXECUTE BOOSTED PROCEDURE db.cdc.* seulement)."""

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def current(self, db: str) -> str:
        with self.driver.session(database=db) as s:
            return s.run("CALL db.cdc.current() YIELD id RETURN id").single()["id"]

    def fetch(self, db: str, cursor: str) -> list[dict]:
        with self.driver.session(database=db) as s:
            rows = s.run("CALL db.cdc.query($c) YIELD id, txId, seq, metadata, event RETURN id, txId, seq, metadata, event",
                         c=cursor).data()
        return to_json(rows)          # dates Neo4j -> chaînes ISO : tout le reste du pipeline manipule du JSON
