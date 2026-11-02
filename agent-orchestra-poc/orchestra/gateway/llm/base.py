from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCallRequest:
    name: str
    args: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class GenResult:
    text: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class LLMProvider(ABC):
    """Single interface: generation, tool calls, embeddings, token counting.

    `contents`: list of {"role": "user"|"model", "text"} | {"role": "model", "tool_calls": [{"name","args"}]}
                 | {"role": "tool", "name", "result": {...}}
    `tools`: declarations {"name", "description", "parameters": <JSON schema>}
    """

    @abstractmethod
    def generate(self, *, model: str, system: str | None, contents: list[dict], tools: list[dict] | None = None) -> GenResult: ...

    @abstractmethod
    def embed(self, texts: list[str], dim: int) -> list[list[float]]: ...

    @abstractmethod
    def count_tokens(self, model: str, contents: list[dict]) -> int: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...
