import os
from dataclasses import dataclass, field

from orchestra.gateway.auth import make_token

LLM_AGENTS = ["coordinateur", "qualite", "ingenierie", "essais", "planification", "interpreteur-bom", "auditeur"]


@dataclass
class RuntimeSettings:
    gateway_url: str = "http://localhost:18000"
    wake_url: str = "ws://localhost:18001"
    master_key: str = ""
    agents: list = field(default_factory=lambda: list(LLM_AGENTS))
    max_turns: int = 10
    max_tool_result_chars: int = 6000
    electorates: dict = field(default_factory=lambda: {"launch_modification": "inbox:comite"})

    def token(self, agent_id: str) -> str:
        """PoC: a single process hosts all runtimes and derives each one's token. Each AgentRunner
        only uses its own; in production, each runtime would receive only its token."""
        return make_token(self.master_key, "svc", agent_id)

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        e = os.environ
        if not e.get("ORCHESTRA_MASTER_KEY"):
            raise RuntimeError("ORCHESTRA_MASTER_KEY is missing: run `make keygen`.")
        return cls(gateway_url=e.get("GATEWAY_URL", "http://gateway:8000"), wake_url=e.get("CDC_WS_URL", "ws://cdc:8001"),
                   master_key=e["ORCHESTRA_MASTER_KEY"], max_turns=int(e.get("RUNTIME_MAX_TURNS", "10")))
