import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    neo4j_uri: str = "bolt://localhost:17687"
    neo4j_user: str = "gateway"
    neo4j_password: str = "gateway-dev-pw"
    db: str = "orchestra"
    kg_user: str = "kgcurator"
    kg_password: str = "kgcurator-dev-pw"
    master_key: str = ""
    data_dir: Path = field(default_factory=lambda: Path("/data"))
    env_llm_key: str | None = None          # valeur initiale tant qu'aucune clé n'est enregistrée dans l'UI
    llm_provider: str = "gemini"
    default_budget: int = 50                # messages par chaîne
    default_token_budget: int = 200_000
    share_ttl_days: int = 30
    max_live_days: int = 30
    embed_dim: int = 768
    embed_model: str = "gemini-embedding-001"
    recall_candidate_factor: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        master = e.get("ORCHESTRA_MASTER_KEY", "")
        if not master:
            raise RuntimeError("ORCHESTRA_MASTER_KEY manquante : lance `make keygen`.")
        return cls(
            neo4j_uri=e.get("NEO4J_URI", cls.neo4j_uri),
            neo4j_user="gateway",
            neo4j_password=e.get("NEO4J_GATEWAY_PASSWORD", cls.neo4j_password),
            db=e.get("ORCHESTRA_DB", "orchestra"),
            kg_password=e.get("NEO4J_KGCURATOR_PASSWORD", cls.kg_password),
            master_key=master,
            data_dir=Path(e.get("ORCHESTRA_DATA_DIR", "/data")),
            env_llm_key=e.get("GEMINI_API_KEY") or None,
            llm_provider=e.get("LLM_PROVIDER", "gemini"),
        )
