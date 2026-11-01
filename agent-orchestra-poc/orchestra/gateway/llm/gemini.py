from google import genai
from google.genai import types

from orchestra.gateway.llm.base import GenResult, LLMProvider, ToolCallRequest, Usage


def _to_contents(contents: list[dict]) -> list[types.Content]:
    out = []
    for c in contents:
        if c["role"] == "tool":
            part = types.Part.from_function_response(name=c["name"], response=c["result"])
            if out and out[-1].role == "user" and out[-1].parts and out[-1].parts[0].function_response is not None:
                out[-1].parts.append(part)          # plusieurs appels d'un même tour : réponses groupées
            else:
                out.append(types.Content(role="user", parts=[part]))
        elif c.get("tool_calls"):
            parts = [types.Part.from_function_call(name=t["name"], args=t["args"]) for t in c["tool_calls"]]
            out.append(types.Content(role="model", parts=parts))
        else:
            out.append(types.Content(role=c["role"], parts=[types.Part.from_text(text=c["text"])]))
    return out


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, embed_model: str = "gemini-embedding-001"):
        self._client = genai.Client(api_key=api_key)
        self._embed_model = embed_model
        self._key = api_key

    def _clean(self, e: Exception) -> Exception:
        return RuntimeError(str(e).replace(self._key, "***"))

    def generate(self, *, model, system, contents, tools=None) -> GenResult:
        cfg = types.GenerateContentConfig(system_instruction=system)
        if tools:
            cfg.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
                for t in tools])]
            cfg.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        try:
            r = self._client.models.generate_content(model=model, contents=_to_contents(contents), config=cfg)
        except Exception as e:
            raise self._clean(e) from None
        calls = [ToolCallRequest(fc.name, dict(fc.args or {})) for fc in (r.function_calls or [])]
        text = None
        try:
            text = r.text if not calls else None
        except Exception:
            pass
        u = r.usage_metadata
        return GenResult(text, calls, Usage(getattr(u, "prompt_token_count", 0) or 0, getattr(u, "candidates_token_count", 0) or 0))

    def embed(self, texts, dim):
        try:
            r = self._client.models.embed_content(model=self._embed_model, contents=texts,
                                                  config=types.EmbedContentConfig(output_dimensionality=dim))
        except Exception as e:
            raise self._clean(e) from None
        return [list(e.values) for e in r.embeddings]

    def count_tokens(self, model, contents):
        try:
            return self._client.models.count_tokens(model=model, contents=_to_contents(contents)).total_tokens or 0
        except Exception as e:
            raise self._clean(e) from None

    def list_models(self):
        try:
            return sorted(m.name.removeprefix("models/") for m in self._client.models.list()
                          if "generateContent" in (m.supported_actions or []))
        except Exception as e:
            raise self._clean(e) from None
