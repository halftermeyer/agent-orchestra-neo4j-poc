"""Stateless service tokens: HMAC(master key, kind:id). The agentId always comes from here (rule 3)."""
import base64
import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, Request

from orchestra.gateway.errors import Forbidden, Unauthorized

KINDS = ("svc", "user", "admin", "sys")


def make_token(master_key: str, kind: str, ident: str) -> str:
    assert kind in KINDS
    body = base64.urlsafe_b64encode(f"{kind}:{ident}".encode()).decode().rstrip("=")
    sig = hmac.new(master_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_token(master_key: str, token: str) -> tuple[str, str]:
    try:
        body, sig = token.split(".", 1)
        good = hmac.new(master_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise ValueError
        kind, ident = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode().split(":", 1)
        if kind not in KINDS:
            raise ValueError
        return kind, ident
    except Exception:
        raise Unauthorized("invalid token") from None


@dataclass(frozen=True)
class Principal:
    kind: str            # svc | user | admin
    id: str
    is_person: bool = False
    role: str | None = None

    @property
    def is_admin(self):
        return self.kind == "admin"


def get_ctx(request: Request):
    return request.app.state.ctx


def principal(request: Request, ctx=Depends(get_ctx)) -> Principal:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized("missing token")
    kind, ident = parse_token(ctx.settings.master_key, header[7:].strip())
    if kind == "admin":
        return Principal("admin", "admin")
    if kind == "sys":
        return Principal("sys", ident)
    row = ctx.store.read(lambda r: r.one("principal", id=ident))
    if row is None:
        raise Unauthorized("unknown agent")
    person = "Person" in row["labels"]
    if (kind == "user") != person:
        raise Unauthorized("token inconsistent with the agent type")
    if row["quarantined"]:
        raise Forbidden("agent is quarantined")
    return Principal(kind, ident, person, row["role"])


def require_admin(p: Principal = Depends(principal)) -> Principal:
    if not p.is_admin:
        raise Forbidden("reserved to the administrator")
    return p


def require_agent(p: Principal = Depends(principal)) -> Principal:
    if p.is_admin or p.kind == "sys":
        raise Forbidden("agent action: a service or user token is required")
    return p


def require_service(p: Principal = Depends(principal)) -> Principal:
    if p.kind != "svc":
        raise Forbidden("reserved to agent runtimes")
    return p


def require_person(p: Principal = Depends(principal)) -> Principal:
    if p.kind != "user":
        raise Forbidden("reserved to people")
    return p


def require_sys(p: Principal = Depends(principal)) -> Principal:
    """System actors (CDC consumer): never an agent, never the UI."""
    if p.kind != "sys":
        raise Forbidden("reserved to the CDC consumer")
    return p
