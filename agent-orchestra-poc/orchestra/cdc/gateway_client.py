import httpx


class GatewayError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"{status} {body[:200]}")
        self.status = status
        self.body = body

    @property
    def transient(self) -> bool:
        return self.status >= 500 or self.status == 0


class GatewayClient:
    """The CDC consumer's only entry point to the graph (writes): the gateway."""

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=10)
        self.h = {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, path, headers=self.h, **kw)
        except httpx.TransportError as e:
            raise GatewayError(0, str(e)) from None
        if r.status_code >= 400:
            raise GatewayError(r.status_code, r.text)
        return r.json()

    def owners(self, inbox: str) -> dict:
        return self._call("GET", f"/internal/inbox/{inbox}/owners")

    def message(self, mid: str) -> dict:
        return self._call("GET", f"/internal/messages/{mid}")

    def topic_routines(self, topic: str) -> list[dict]:
        return self._call("GET", f"/internal/topics/{topic}/routines")["routines"]

    def due(self, now_iso: str) -> list[dict]:
        return self._call("GET", "/internal/routines/due", params={"now": now_iso})["routines"]

    def advance(self, rid: str, **body) -> dict:
        return self._call("POST", f"/internal/routines/{rid}/advance", json=body)

    def deliver(self, **body) -> dict:
        return self._call("POST", "/internal/deliver", json=body)

    def sync_ref(self, **body) -> dict:
        return self._call("POST", "/internal/entityrefs/sync", json=body)


def check_token(http: httpx.Client, token: str) -> dict | None:
    r = http.get("/auth/check", headers={"Authorization": f"Bearer {token}"})
    return r.json() if r.status_code == 200 else None
