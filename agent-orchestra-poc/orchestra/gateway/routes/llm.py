from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_service
from orchestra.gateway.errors import BudgetExhausted, Conflict, Forbidden
from orchestra.gateway.routes.core import Strict, load_session
from orchestra.gateway.tool_specs import TOOL_SPECS

router = APIRouter()


class ToolCallIn(Strict):
    name: str
    args: dict = {}


class Content(Strict):
    role: Literal["user", "model", "tool"]
    text: str | None = Field(default=None, max_length=50000)
    tool_calls: list[ToolCallIn] | None = None
    name: str | None = None
    result: dict | None = None


class Generate(Strict):
    sessionId: str
    contents: list[Content] = Field(min_length=1, max_length=200)
    system: str | None = Field(default=None, max_length=20000)
    tools: list[str] = []


@router.post("/llm/generate")
def generate(b: Generate, p: Principal = Depends(require_service), ctx=Depends(get_ctx)):
    """Appel LLM pour le compte d'un runtime : modèle imposé par l'AgentVersion, outils filtrés par CAN_USE,
    budget de tokens vérifié avant l'appel, consommation réelle imputée à la chaîne après."""
    s = load_session(ctx, p, b.sessionId)
    me = ctx.store.read(lambda r: r.one("me", agentId=p.id))
    model = (me["version"] or {}).get("model")
    if not model:
        raise Conflict("this agent has no model (rule-based agent)")
    allowed = {t["name"] for t in me["tools"]}
    bad = [t for t in b.tools if t not in allowed or t not in TOOL_SPECS]
    if bad:
        raise Forbidden(f"tools not allowed: {bad}")
    st = ctx.settings
    meta = {"agentId": p.id, "chainId": s["chainId"]}
    chk = ctx.store.write(meta, lambda r: r.one("chain_tokens_check", chainId=s["chainId"], agentId=p.id,
                                               defaultBudget=st.default_budget, defaultTokenBudget=st.default_token_budget))
    if chk["status"] != "active":
        raise Conflict(f"chain {chk['status']}")
    if chk["tokensSpent"] >= chk["tokenBudget"]:
        raise BudgetExhausted("chain token budget exhausted")
    res = ctx.llm().generate(
        model=model, system=b.system, contents=[c.model_dump(exclude_none=True) for c in b.contents],
        tools=[{"name": t, **TOOL_SPECS[t]} for t in b.tools] or None)
    after = ctx.store.write(meta, lambda r: r.one("chain_tokens_add", chainId=s["chainId"], tokens=res.usage.total))
    return {"text": res.text, "toolCalls": [{"name": c.name, "args": c.args} for c in res.tool_calls],
            "usage": {"input": res.usage.input_tokens, "output": res.usage.output_tokens},
            "chain": {"status": after["status"], "tokensSpent": after["tokensSpent"], "tokenBudget": after["tokenBudget"]}}
