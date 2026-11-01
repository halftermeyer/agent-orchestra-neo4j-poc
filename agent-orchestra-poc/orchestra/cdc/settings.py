import os
from dataclasses import dataclass, field
from pathlib import Path

from orchestra.gateway.auth import make_token


@dataclass
class CdcSettings:
    neo4j_uri: str = "bolt://localhost:17687"
    neo4j_user: str = "cdc"
    neo4j_password: str = "cdc-dev-pw"
    orchestra_db: str = "orchestra"
    kg_dbs: dict = field(default_factory=lambda: {"kgproduit": "produit", "kgprojet": "projet"})  # base -> id du KG
    bridge_dbs: tuple = ("kgproduit",)       # KG dont le pont publie dans kg.<id>.raw
    bridge_agent: str = "pont-kg"
    gateway_url: str = "http://localhost:18000"
    sys_token: str = ""
    data_dir: Path = field(default_factory=lambda: Path("/data"))
    poll_interval: float = 0.1               # secondes (spike 6 : p50 ≈ 70 ms)
    scheduler_interval: float = 1.0
    misfire_grace: float = 60.0              # secondes ; au-delà, un créneau `skip` est ignoré
    owners_ttl: float = 10.0
    max_changes_in_raw: int = 200

    @property
    def dbs(self) -> list[str]:
        return [self.orchestra_db, *self.kg_dbs]

    @classmethod
    def from_env(cls) -> "CdcSettings":
        e = os.environ
        master = e.get("ORCHESTRA_MASTER_KEY", "")
        if not master:
            raise RuntimeError("ORCHESTRA_MASTER_KEY manquante : lance `make keygen`.")
        return cls(
            neo4j_uri=e.get("NEO4J_URI", cls.neo4j_uri),
            neo4j_password=e.get("NEO4J_CDC_PASSWORD", cls.neo4j_password),
            orchestra_db=e.get("ORCHESTRA_DB", "orchestra"),
            gateway_url=e.get("GATEWAY_URL", "http://gateway:8000"),
            sys_token=make_token(master, "sys", "cdc"),
            data_dir=Path(e.get("CDC_DATA_DIR", "/data")),
            poll_interval=float(e.get("CDC_POLL_INTERVAL", "0.1")),
        )
