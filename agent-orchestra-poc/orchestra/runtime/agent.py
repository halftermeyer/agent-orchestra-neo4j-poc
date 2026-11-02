import json
import logging
from datetime import datetime, timezone

from orchestra.gateway.tool_specs import TOOL_SPECS
from orchestra.runtime.client import ClientError
from orchestra.runtime.tools import ToolExecutor

log = logging.getLogger("orchestra.runtime")

COMMON_RULES = """Common rules:
- Act only through your tools. Never invent an identifier (part, test, task, agent): read it from the messages or query a graph.
- Call `set_status` first with a short sentence, then work. No pleasantries or acknowledgements: only send a message if it carries an action or useful information.
- Always answer within the current chain (this is automatic). When you are done, stop calling tools and finish with a one-sentence summary.
- Recipient names for `send_message` are those in the "Allowed recipients" list.
- Write every message, status and fact in English."""


def _compact(x):
    """Slim down the payload shown to the LLM: technical CDC event identifiers do not help it."""
    if isinstance(x, dict):
        return {k: _compact(v) for k, v in x.items() if k != "eventId"}
    if isinstance(x, list):
        return [_compact(v) for v in x]
    return x


def _fmt_msg(m: dict, me: str) -> str:
    payload = f" payload={json.dumps(m['payload'], ensure_ascii=False)}" if m.get("payload") else ""
    return f"- {m['createdAt'][11:19]} {m['from']} → {', '.join(x.removeprefix('inbox:') for x in m['to'])} [{m['performative']}] {m['body'] or ''}{payload}"


class AgentRunner:
    """Generic LLM agent loop: wake-up → session → (generation ↔ tools)* → close."""

    def __init__(self, agent_id: str, client, settings):
        self.agent, self.c, self.s = agent_id, client, settings
        self._templates = None

    # ----- contexte -----
    def system_prompt(self, me: dict) -> str:
        v, m = me["version"] or {}, me["mandate"] or {}
        if self._templates is None:
            self._templates = self.c.templates() if me["kgs"] else []
        tpl = "\n".join(
            f"  - kg=\"{t['kg']}\", template=\"{t['name']}\", params={{{', '.join(f'\"{k}\": <{v}>' for k, v in t['params'].items())}}}"
            for t in self._templates if t["kg"] in me["kgs"] or t["kg"] == "federated" and set(me["kgs"]) >= {"produit", "projet"})
        commitments = self.c.open_commitments()
        parts = [v.get("prompt") or "", COMMON_RULES,
                 f"Your identifier: {self.agent}. Date (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}.",
                 f"Your mandate: {m.get('purpose')}. Scope: {m.get('scope')}. Success criterion: {m.get('successCriteria')}.",
                 "Allowed recipients: " + ", ".join(sorted(x.removeprefix("inbox:") for x in me["canSendTo"]))]
        if tpl:
            parts.append("Graphs you can query with `query_kg`: pass EXACTLY these values (the template name alone, no parentheses or prefix; "
                         "parameters go in `params`). For the `about` keys of `remember`, use db = kgproduit or kgprojet:\n" + tpl)
        if commitments:
            parts.append("Open commitments (settle them with `commit` and `fulfills`):\n" + "\n".join(
                f"  - {c['id']} to {c['toAgent']} before {c['dueAt'][:16]}: {c['description']}" for c in commitments))
        return "\n\n".join(parts)

    def user_message(self, msg: dict, thread: list[dict]) -> str:
        lines = [f"You were woken by a message from {msg['from']} ({msg['performative']}) in chain {msg['chainId']}:",
                 msg["body"] or "(no text)"]
        if msg.get("payload"):
            lines.append("Attached data: " + json.dumps(_compact(msg["payload"]), ensure_ascii=False, separators=(",", ":")))
        if msg.get("hasSharedMemory"):
            lines.append("A memory was shared with you along with this message: read it with `recall`.")
        earlier = [m for m in thread if m["id"] != msg["id"]]
        if earlier:
            lines.append("Conversation thread (what you sent or received before):\n" + "\n".join(_fmt_msg(m, self.agent) for m in earlier))
        return "\n".join(lines)

    # ----- session lifecycle -----
    def gate(self, msg: dict) -> str | None:
        """Rule gates, before any LLM call: return a reason not to wake the LLM."""
        p = msg.get("payload") or {}
        if p.get("kind") == "commitment-due":
            try:
                if self.c.commitment(p["commitmentId"])["status"] != "open":
                    return "commitment already settled"
            except ClientError:
                pass
        return None

    def handle(self, message_id: str) -> str:
        try:
            sess = self.c.open_session(message_id)
        except ClientError as e:
            log.warning("%s: session refused for %s (%s)", self.agent, message_id, e.status)
            return "refused"
        if sess.get("closedAt"):
            return "already-done"
        sid, status = sess["id"], "completed"
        try:
            msg = self.c.message(message_id)
            reason = self.gate(msg)
            if reason:
                log.info("%s: %s — no LLM call (%s)", self.agent, message_id[:12], reason)
            else:
                status = self.work(sid, msg)
        except ClientError as e:                       # budget exhausted, chain suspended, LLM unavailable...
            log.warning("%s: session %s failed (%s %s)", self.agent, sid, e.status, e.body[:120])
            status = "failed"
        except Exception:
            log.exception("%s: internal error", self.agent)
            status = "failed"
        try:
            self.c.close_session(sid, status)
        except ClientError:
            pass
        return status

    def work(self, sid: str, msg: dict) -> str:
        me = self.c.me()
        thread = self.c.thread(msg["chainId"])
        return self.converse(sid, msg, me, [{"role": "user", "text": self.user_message(msg, thread)}])

    def converse(self, sid: str, msg: dict, me: dict, contents: list[dict], key_prefix: str = "t") -> str:
        if self._templates is None:
            self._templates = self.c.templates() if me["kgs"] else []
        tools = ToolExecutor(self.c, self.s, self.agent, sid, msg["id"], me["canSendTo"], self._templates)
        names = [t["name"] for t in me["tools"] if t["name"] in TOOL_SPECS]
        system = self.system_prompt(me)
        for turn in range(self.s.max_turns):
            r = self.c.generate(sessionId=sid, contents=contents, system=system, tools=names)
            if not r["toolCalls"]:
                return "completed"
            contents.append({"role": "model", "tool_calls": r["toolCalls"]})
            for i, call in enumerate(r["toolCalls"]):
                result = tools.run(call["name"], call["args"], f"{key_prefix}{turn}.{i}-{sid[-12:]}")
                contents.append({"role": "tool", "name": call["name"], "result": result if isinstance(result, dict) else {"result": result}})
            if tools.awaiting_approval:
                return "input-required"
        log.warning("%s: turn limit of %d reached", self.agent, self.s.max_turns)
        return "failed"
