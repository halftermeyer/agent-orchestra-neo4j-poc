import uuid
from dataclasses import dataclass
from typing import Callable

from orchestra.gateway.errors import NotConfigured
from orchestra.gateway.keystore import KeyStore
from orchestra.gateway.llm.base import LLMProvider
from orchestra.gateway.settings import Settings
from orchestra.gateway.store import Store


def default_llm_factory(settings: Settings) -> Callable[[str], LLMProvider]:
    def make(key: str) -> LLMProvider:
        if settings.llm_provider != "gemini":
            raise NotConfigured(f"unknown provider: {settings.llm_provider}")
        from orchestra.gateway.llm.gemini import GeminiProvider
        return GeminiProvider(key, settings.embed_model)
    return make


@dataclass
class Ctx:
    settings: Settings
    store: Store
    keystore: KeyStore
    llm_factory: Callable[[str], LLMProvider]

    def llm(self, key: str | None = None) -> LLMProvider:
        key = key or self.keystore.get()
        if not key:
            raise NotConfigured("no LLM key: Settings → Models")
        return self.llm_factory(key)

    def log_access(self, agent_id: str, kind: str, granted: bool, targets: list[str], detail: str = "", chain_id: str = "none"):
        """Journal des accès dans le graphe (append-only)."""
        self.store.write({"agentId": agent_id, "chainId": chain_id}, lambda r: r.one(
            "access_log", id=uuid.uuid4().hex, agentId=agent_id, kind=kind, granted=granted,
            targets=targets, count=len(targets), detail=detail[:200]))
