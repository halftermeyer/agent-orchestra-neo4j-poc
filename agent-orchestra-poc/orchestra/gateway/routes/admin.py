from fastapi import APIRouter, Depends
from pydantic import Field

from orchestra.gateway.auth import Principal, get_ctx, require_admin
from orchestra.gateway.errors import Conflict, Forbidden, NotFound
from orchestra.gateway.routes.core import Strict
from orchestra.gateway.store import to_json

router = APIRouter()


class Supervise(Strict):
    supervisor: str
    subordinate: str


@router.post("/admin/supervises", status_code=201)
def create_supervises(b: Supervise, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Privileged operation: lock both nodes, then check for cycles, in the same transaction."""
    def tx(r):
        chk = r.one("supervises_lock", **{"from": b.supervisor, "to": b.subordinate})
        if chk is None:
            raise NotFound("agent not found")
        if chk["self"]:
            raise Conflict("an agent cannot supervise itself")
        if chk["cycle"]:
            raise Conflict("this supervision would create a cycle")
        if chk["softwareOverPerson"]:
            raise Forbidden("a software agent does not supervise a human")
        return r.one("supervises_create", **{"from": b.supervisor, "to": b.subordinate})
    return to_json(ctx.store.write({"agentId": p.id, "chainId": "none"}, tx))


class NewVersion(Strict):
    model: str | None = None
    prompt: str | None = None


@router.post("/admin/agents/{agent_id}/versions", status_code=201)
def new_version(agent_id: str, b: NewVersion, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Changing the model or prompt creates a new AgentVersion (SUPERSEDES)."""
    row = ctx.store.write({"agentId": p.id, "chainId": "none"}, lambda r: r.one(
        "version_create", agentId=agent_id, by=p.id, model=b.model, prompt=b.prompt))
    if row is None:
        raise NotFound("software agent not found")
    return to_json(row)


# ---------- Settings → Models ----------
class SetKey(Strict):
    apiKey: str = Field(min_length=8, max_length=512)


class TestKey(Strict):
    apiKey: str | None = Field(default=None, min_length=8, max_length=512)


class Select(Strict):
    model: str = Field(min_length=1, max_length=200)


@router.get("/settings/models")
def models_status(p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Write-only: only the last 4 characters and the date are shown back."""
    return {**ctx.keystore.status(), "provider": ctx.settings.llm_provider, "model": ctx.keystore.get_model()}


@router.put("/settings/models/key")
def set_key(b: SetKey, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    ctx.keystore.set(b.apiKey)
    return ctx.keystore.status()


@router.delete("/settings/models/key")
def delete_key(p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    ctx.keystore.delete()
    return ctx.keystore.status()


@router.post("/settings/models/test")
def test_key(b: TestKey, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    """Validates the key (candidate or saved) by listing the models."""
    try:
        models = ctx.llm(b.apiKey).list_models()
    except Exception as e:
        msg = str(e)
        if b.apiKey:
            msg = msg.replace(b.apiKey, "***")
        return {"ok": False, "error": msg[:300], "models": []}
    return {"ok": True, "models": models}


@router.put("/settings/models/selection")
def select_model(b: Select, p: Principal = Depends(require_admin), ctx=Depends(get_ctx)):
    ctx.keystore.set_model(b.model)
    return {"model": b.model}
