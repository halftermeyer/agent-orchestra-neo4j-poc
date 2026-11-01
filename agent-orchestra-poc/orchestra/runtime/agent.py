import json
import logging
from datetime import datetime, timezone

from orchestra.gateway.tool_specs import TOOL_SPECS
from orchestra.runtime.client import ClientError
from orchestra.runtime.tools import ToolExecutor

log = logging.getLogger("orchestra.runtime")

COMMON_RULES = """Règles communes :
- Agis uniquement par tes outils. N'invente jamais d'identifiant (pièce, essai, tâche, agent) : lis-les dans les messages ou interroge un graphe.
- Appelle `set_status` au début avec une phrase courte, puis travaille. Pas de message de politesse ni d'accusé de réception : n'envoie un message que s'il porte une action ou une information utile.
- Réponds toujours dans la chaîne en cours (c'est automatique). Quand tu as fini, n'appelle plus d'outil et termine par une phrase de bilan.
- Les noms de destinataires de `send_message` sont ceux de la liste « Destinataires autorisés »."""


def _compact(x):
    """Allège le payload montré au LLM : les identifiants techniques d'événements CDC ne l'aident pas."""
    if isinstance(x, dict):
        return {k: _compact(v) for k, v in x.items() if k != "eventId"}
    if isinstance(x, list):
        return [_compact(v) for v in x]
    return x


def _fmt_msg(m: dict, me: str) -> str:
    payload = f" payload={json.dumps(m['payload'], ensure_ascii=False)}" if m.get("payload") else ""
    return f"- {m['createdAt'][11:19]} {m['from']} → {', '.join(x.removeprefix('inbox:') for x in m['to'])} [{m['performative']}] {m['body'] or ''}{payload}"


class AgentRunner:
    """Boucle générique d'un agent LLM : réveil → session → (génération ↔ outils)* → fermeture."""

    def __init__(self, agent_id: str, client, settings):
        self.agent, self.c, self.s = agent_id, client, settings
        self._templates = None

    # ----- contexte -----
    def system_prompt(self, me: dict) -> str:
        v, m = me["version"] or {}, me["mandate"] or {}
        if self._templates is None:
            self._templates = self.c.templates() if me["kgs"] else []
        tpl = "\n".join(f"  - {t['kg']}/{t['name']}({', '.join(f'{k}: {v}' for k, v in t['params'].items())})" for t in self._templates
                        if t["kg"] in me["kgs"] or t["kg"] == "federated" and set(me["kgs"]) >= {"produit", "projet"})
        commitments = self.c.open_commitments()
        parts = [v.get("prompt") or "", COMMON_RULES,
                 f"Ton identifiant : {self.agent}. Date (UTC) : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}.",
                 f"Ton mandat : {m.get('purpose')}. Périmètre : {m.get('scope')}. Critère de réussite : {m.get('successCriteria')}.",
                 "Destinataires autorisés : " + ", ".join(sorted(x.removeprefix("inbox:") for x in me["canSendTo"]))]
        if tpl:
            parts.append("Graphes interrogeables avec `query_kg` (kg/modèle(paramètres)) ; pour les clés `about` de `remember`, utilise "
                         "db = kgproduit ou kgprojet :\n" + tpl)
        if commitments:
            parts.append("Engagements ouverts (solde-les avec `commit` et `fulfills`) :\n" + "\n".join(
                f"  - {c['id']} envers {c['toAgent']} avant {c['dueAt'][:16]} : {c['description']}" for c in commitments))
        return "\n\n".join(parts)

    def user_message(self, msg: dict, thread: list[dict]) -> str:
        lines = [f"Tu es réveillé par un message de {msg['from']} ({msg['performative']}) dans la chaîne {msg['chainId']} :",
                 msg["body"] or "(sans texte)"]
        if msg.get("payload"):
            lines.append("Données jointes : " + json.dumps(_compact(msg["payload"]), ensure_ascii=False, separators=(",", ":")))
        if msg.get("hasSharedMemory"):
            lines.append("Une mémoire t'a été partagée avec ce message : consulte-la avec `recall`.")
        earlier = [m for m in thread if m["id"] != msg["id"]]
        if earlier:
            lines.append("Fil de la conversation (ce que tu as envoyé ou reçu avant) :\n" + "\n".join(_fmt_msg(m, self.agent) for m in earlier))
        return "\n".join(lines)

    # ----- cycle d'une session -----
    def gate(self, msg: dict) -> str | None:
        """Portes à règles, avant tout appel LLM : retourne une raison de ne pas réveiller le LLM."""
        p = msg.get("payload") or {}
        if p.get("kind") == "commitment-due":
            try:
                if self.c.commitment(p["commitmentId"])["status"] != "open":
                    return "engagement déjà soldé"
            except ClientError:
                pass
        return None

    def handle(self, message_id: str) -> str:
        try:
            sess = self.c.open_session(message_id)
        except ClientError as e:
            log.warning("%s : session refusée pour %s (%s)", self.agent, message_id, e.status)
            return "refused"
        if sess.get("closedAt"):
            return "already-done"
        sid, status = sess["id"], "completed"
        try:
            msg = self.c.message(message_id)
            reason = self.gate(msg)
            if reason:
                log.info("%s : %s — pas de LLM (%s)", self.agent, message_id[:12], reason)
            else:
                status = self.work(sid, msg)
        except ClientError as e:                       # budget épuisé, chaîne suspendue, LLM indisponible…
            log.warning("%s : session %s en échec (%s %s)", self.agent, sid, e.status, e.body[:120])
            status = "failed"
        except Exception:
            log.exception("%s : erreur interne", self.agent)
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
        tools = ToolExecutor(self.c, self.s, self.agent, sid, msg["id"], me["canSendTo"])
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
        log.warning("%s : limite de %d tours atteinte", self.agent, self.s.max_turns)
        return "failed"
