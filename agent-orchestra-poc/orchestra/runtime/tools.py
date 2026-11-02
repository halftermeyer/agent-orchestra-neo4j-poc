"""Exécution des outils appelés par le LLM. Chaque appel est tracé (ToolCall) ; `agentId` n'est jamais un argument."""
import json
import logging

from orchestra.runtime import cpa
from orchestra.runtime.client import ClientError

log = logging.getLogger("orchestra.runtime")


def _short(x, limit):
    s = json.dumps(x, ensure_ascii=False, default=str)
    return x if len(s) <= limit else {"truncated": True, "preview": s[:limit]}


class ToolExecutor:
    def __init__(self, client, settings, agent_id: str, session_id: str, trigger_id: str, can_send_to: list[str], templates: list[dict] | None = None):
        self.c, self.s, self.agent, self.sid, self.trigger = client, settings, agent_id, session_id, trigger_id
        self.templates = templates or []
        self.can_send_to = set(can_send_to)
        self.awaiting_approval = False
        self.sent = 0

    # ----- résolution des destinataires : l'agent parle par noms, la passerelle par inbox autorisées -----
    def _inbox(self, name: str) -> str | None:
        for cand in (f"inbox:{name}", name):
            if cand in self.can_send_to:
                return cand
        return None

    def run(self, name: str, args: dict, key: str) -> dict:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return {"error": f"outil inconnu : {name}"}
        if name == "launch_modification":              # clos l'appel créé par la validation, pas un nouvel appel
            return self._guard(lambda: handler(args, key))
        try:
            self.c.post("/tools/calls", {"sessionId": self.sid, "tool": name, "idempotencyKey": key, "args": _short(args, 1500)})
        except ClientError as e:
            return {"error": f"outil refusé par la passerelle ({e.status}) : {e.body[:200]}"}
        fact_id = msg_id = None
        try:
            result, produced = handler(args, key)
            fact_id, msg_id = produced.get("factId"), produced.get("messageId")
            if "error" in result:                      # refus métier (destinataire, outil sans effet…) : l'appel est en échec
                self.c.post(f"/tools/calls/{key}/end", {"status": "failed", "error": str(result["error"])[:300]})
            else:
                self.c.post(f"/tools/calls/{key}/end", {"status": "completed", "factId": fact_id, "messageId": msg_id})
            return _short(result, self.s.max_tool_result_chars)
        except ClientError as e:
            self.c.post(f"/tools/calls/{key}/end", {"status": "failed", "error": f"{e.status} {e.body[:300]}"})
            return {"error": f"{e.status} {e.body[:300]}"}
        except Exception as e:                           # bug d'outil : l'agent le voit, l'appel est clos en échec
            self.c.post(f"/tools/calls/{key}/end", {"status": "failed", "error": f"{type(e).__name__}: {e}"[:300]})
            return {"error": f"{type(e).__name__}: {e}"}

    def _guard(self, fn):
        try:
            return _short(fn(), self.s.max_tool_result_chars)
        except ClientError as e:
            return {"error": f"{e.status} {e.body[:300]}"}

    # ----- outils -----
    def _t_send_message(self, a, key):
        to = a.get("to") or []
        to = [to] if isinstance(to, str) else to
        inboxes, unknown = [], []
        for n in to:
            (inboxes if self._inbox(n) else unknown).append(self._inbox(n) or n)
        if unknown:
            return {"error": f"destinataires non autorisés : {unknown}. Autorisés : {sorted(self._allowed_names())}"}, {}
        body = {"to": inboxes, "performative": a.get("performative", "inform"), "body": a.get("body", ""),
                "sessionId": self.sid, "inReplyTo": self.trigger}
        if a.get("payload"):
            body["payload"] = a["payload"]
        if a.get("attach_memory"):
            body["attachMemory"] = {"mode": "snapshot"}
        r = self.c.post("/messages", body)
        self.sent += 1
        return {"sent": True, "messageId": r["id"], "to": to}, {"messageId": r["id"]}

    def _allowed_names(self):
        return {x.removeprefix("inbox:") for x in self.can_send_to}

    def _t_set_status(self, a, key):
        self.c.post("/status", {"sessionId": self.sid, "text": str(a.get("text", ""))[:280]})
        return {"ok": True}, {}

    def _t_remember(self, a, key):
        about = []
        for x in a.get("about") or []:
            db = x.get("db", "")
            about.append({"db": db if db.startswith("kg") else f"kg{db}", "key": x["key"], "label": str(x.get("label", x["key"]))[:200]})
        r = self.c.post("/facts", {"sessionId": self.sid, "statement": a["statement"], "confidence": float(a.get("confidence", 0.8)), "about": about})
        return {"remembered": True, "factId": r["id"]}, {"factId": r["id"]}

    def _t_recall(self, a, key):
        r = self.c.post("/recall", {"query": a["query"], "k": 6})
        return {"facts": [{"statement": f["statement"], "memory": f["memoryId"], "since": f["validFrom"]} for f in r["facts"]]}, {}

    def _t_query_kg(self, a, key):
        kg, tpl, params = a.get("kg", ""), a.get("template", ""), a.get("params") or {}
        # tolérance : les LLM recopient parfois la signature du catalogue (« produit/part_info(partId) »)
        if "/" in tpl:
            prefix, tpl = tpl.split("/", 1)
            kg = kg or prefix
        tpl = tpl.split("(")[0].strip()
        if not kg:                                   # graphe omis : on le déduit du catalogue
            kg = next((t["kg"] for t in self.templates if t["name"] == tpl), "")
        if kg == "federated":
            r = self.c.post("/kg/federated", {"template": tpl, "params": params})
        else:
            r = self.c.post("/kg/query", {"kg": kg, "template": tpl, "params": params})
        rows = r["rows"]
        return {"rows": rows[:40], "rowCount": len(rows)}, {}

    def _t_commit(self, a, key):
        if a.get("fulfills"):
            r = self.c.post(f"/commitments/{a['fulfills']}/fulfill")
            return {"fulfilled": a["fulfills"]}, {}
        r = self.c.post("/commitments", {"sessionId": self.sid, "to": a["to"], "description": a["description"],
                                         "dueInMinutes": int(a.get("due_in_minutes", 30))})
        return {"commitmentId": r["id"], "dueAt": r["dueAt"]}, {}

    def _t_request_approval(self, a, key):
        tool = a.get("tool", "")
        electorate = self.s.electorates.get(tool)
        if not electorate:
            return {"error": f"aucun électorat défini pour l'outil {tool}"}, {}
        r = self.c.post("/approvals", {"sessionId": self.sid, "tool": tool, "idempotencyKey": f"{key}-approval", "electorate": electorate,
                                       "args": {"part_id": a.get("part_id"), "replacement_id": a.get("replacement_id"),
                                                "description": a.get("description")}})
        self.awaiting_approval = True
        return {"approvalId": r["id"], "status": r.get("status", "pending"),
                "note": "En attente du vote du comité ; tu seras réveillé à la décision. Termine ton tour."}, {}

    def _t_launch_modification(self, a, key):
        ap = self.c.approval(a["approval_id"])
        tc_key = ap["toolCallKey"].split(":", 1)[1]
        out = self.c.post("/modifications/launch", {"sessionId": self.sid, "toolCallKey": tc_key})
        self.c.post(f"/tools/calls/{tc_key}/end", {"status": "completed"})
        return out

    def _t_cpa_simulate(self, a, key):
        rows = self.c.post("/kg/query", {"kg": "projet", "template": "project_graph", "params": {}})["rows"]
        tasks = [{"id": r["id"], "name": r["name"], "durationDays": r["durationDays"], "dependsOn": r["dependsOn"]} for r in rows]
        try:
            if int(a.get("delay_days", 0)) == 0:
                base = cpa.critical_path(tasks)
                return {"projectDays": base["projectDays"], "criticalPath": base["criticalPath"]}, {}
            return cpa.simulate_delay(tasks, a["task_id"], int(a["delay_days"])), {}
        except KeyError:
            return {"error": f"tâche inconnue : {a.get('task_id')}"}, {}

    def _t_suspend_chain(self, a, key):
        r = self.c.post(f"/chains/{a['chain_id']}/suspend", {"reason": a.get("reason", "")[:500]})
        return {"suspended": a["chain_id"], "status": r["status"]}, {}

    def _t_quarantine_agent(self, a, key):
        self.c.post(f"/agents/{a['target']}/quarantine", {"reason": a.get("reason", "")[:500]})
        return {"quarantined": a["target"]}, {}
