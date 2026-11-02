import json
import logging

from orchestra.runtime.agent import AgentRunner

log = logging.getLogger("orchestra.runtime")


class AuditorRunner(AgentRunner):
    """Signaux d'abord (graphe), LLM seulement sur les candidats. Pouvoir limité à la suspension / quarantaine."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.judged: dict[str, int] = {}          # chaîne -> nombre de messages déjà jugés

    def work(self, sid: str, msg: dict) -> str:
        kind = (msg.get("payload") or {}).get("kind")
        if kind != "audit-scan":
            return super().work(sid, msg)          # ex. chain-suspended : le LLM prévient les humains
        me = self.c.me()
        status = "completed"
        cands = self.c.audit_scan()["candidates"]
        fresh = [c for c in cands if self.judged.get(c["chainId"]) != c["messages"]]   # rien de neuf : pas de nouveau jugement
        log.info("auditor: %d candidate(s), %d to judge", len(cands), len(fresh))
        for c in fresh[:3]:
            self.judged[c["chainId"]] = c["messages"]
            episode = self.c.audit_episode(c["chainId"])
            text = ("A chain is a candidate for audit. Signals computed in the graph:\n"
                    + json.dumps(c, ensure_ascii=False, indent=1)
                    + "\n\nLatest messages of the audited agents (oldest to newest):\n"
                    + "\n".join(f"- {m['from']} → {', '.join(x.removeprefix('inbox:') for x in m['to'])} [{m['performative']}] {m['body']}" for m in episode)
                    + "\n\nDecide: if this is an unproductive loop (the same exchanges repeated without progress, other than a declared "
                      "loop that is progressing), call `suspend_chain` with a precise reason, then warn the humans with `send_message`. "
                      "If the loop is legitimate or is progressing, do nothing.")
            r = self.converse(sid, msg, me, [{"role": "user", "text": text}], key_prefix=f"a{len(self.judged)}-")
            if r == "failed":
                status = "failed"
        return status
