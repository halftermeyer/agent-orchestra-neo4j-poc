import httpx


class ClientError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"{status} {body[:300]}")
        self.status, self.body = status, body


class AgentClient:
    """Le runtime n'a ni clé LLM ni accès à la base : tout passe par la passerelle, avec le jeton de cet agent."""

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=90)
        self.h = {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, path, headers=self.h, **kw)
        except httpx.TransportError as e:
            raise ClientError(0, str(e)) from None
        if r.status_code >= 400:
            raise ClientError(r.status_code, r.text)
        return r.json()

    get = lambda self, path, **kw: self._call("GET", path, **kw)
    post = lambda self, path, body=None, **kw: self._call("POST", path, json=body or {}, **kw)

    def me(self): return self.get("/me")
    def pending(self): return self.get("/inbox/pending")["pending"]
    def message(self, mid): return self.get(f"/inbox/messages/{mid}")
    def thread(self, chain, limit=12): return self.get(f"/threads/{chain}", params={"limit": limit})["messages"]
    def templates(self): return self.get("/kg/templates")["templates"]
    def open_commitments(self): return self.get("/commitments")["commitments"]
    def commitment(self, cid): return self.get(f"/commitments/{cid}")
    def open_session(self, mid): return self.post("/sessions", {"messageId": mid})
    def close_session(self, sid, status): return self.post(f"/sessions/{sid}/close", {"status": status})
    def generate(self, **body): return self.post("/llm/generate", body)
    def audit_scan(self): return self.post("/audit/scan", {})
    def audit_episode(self, chain): return self.get(f"/audit/chains/{chain}/episode")["messages"]
    def approval(self, aid): return self.get(f"/approvals/{aid}")
