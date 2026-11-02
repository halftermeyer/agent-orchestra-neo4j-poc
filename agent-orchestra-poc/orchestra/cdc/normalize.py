"""Événements CDC de la base d'orchestration -> flux normalisé {t, type, actor, target, payload}.

Aucune lecture dans la base : on n'utilise que les `keys` (clés de nœud), les propriétés et le `txMetadata`.
type ∈ woken | status | tool.start | tool.end | sent | learned | vote | waiting | idle | error
"""


def _key(ref: dict, label: str, prop: str):
    for k in (ref or {}).get("keys", {}).get(label, []):
        if prop in k:
            return k[prop]
    return None


def _ts(meta: dict) -> str:
    return meta.get("txCommitTime", "")


def _props(ev: dict, side: str) -> dict:
    st = (ev.get("state") or {}).get(side)
    return (st or {}).get("properties", {}) if st else {}


def agent_of_session(trigger_key: str | None) -> str | None:
    """Clé de session `<messageId>@<agentId>` (écart documenté en phase 2)."""
    return trigger_key.rsplit("@", 1)[1] if trigger_key and "@" in trigger_key else None


def agent_of_toolcall(key: str | None) -> str | None:
    return key.split(":", 1)[0] if key and ":" in key else None


def normalize_tx(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Retourne (événements du flux, créations de RECEIVED à traiter par le consommateur)."""
    nodes = {}                      # elementId -> événement nœud (même transaction)
    tool_of, status_agent = {}, {}
    for e in events:
        ev = e["event"]
        if ev["eventType"] == "n":
            nodes[ev["elementId"]] = ev
        elif ev["eventType"] == "r" and ev["operation"] == "c":
            if ev["type"] == "OF":
                tool_of[_key(ev["start"], "ToolCall", "idempotencyKey")] = _key(ev["end"], "Tool", "name")
            elif ev["type"] == "STATUS":
                status_agent[ev["end"]["elementId"]] = agent_of_session(_key(ev["start"], "Session", "triggerMsgId"))
    out, received = [], []
    for e in events:
        ev, t = e["event"], _ts(e["metadata"])
        op = ev["operation"]
        emit = lambda type_, actor, target=None, **payload: out.append(
            {"t": t, "type": type_, "actor": actor, "target": target, "payload": payload})
        if ev["eventType"] == "n":
            labels, after, before = set(ev["labels"]), _props(ev, "after"), _props(ev, "before")
            if "Fact" in labels and op == "c":
                mem = after.get("memoryId", "")
                emit("learned", mem.removeprefix("mem:"), mem, factId=after.get("id"), statement=(after.get("statement") or "")[:140])
            elif "Commitment" in labels and op == "c":
                emit("waiting", after.get("agentId"), after.get("toAgent"), commitmentId=after.get("id"),
                     dueAt=after.get("dueAt"), description=(after.get("description") or "")[:140])
            elif "StatusUpdate" in labels and op == "c":
                emit("status", status_agent.get(ev["elementId"]), None, text=after.get("text"))
            elif "ToolCall" in labels:
                key, actor = after.get("idempotencyKey") or before.get("idempotencyKey"), after.get("agentId") or before.get("agentId")
                tool = after.get("tool") or before.get("tool") or tool_of.get(key)   # `tool` est dénormalisé : la fin d'un appel est une autre transaction
                if op == "c":
                    st = after.get("status")
                    emit("waiting" if st == "input-required" else "tool.start", actor, tool, key=key, status=st)
                elif op == "u" and before.get("status") != after.get("status"):
                    new = after.get("status")
                    if new == "working":
                        emit("tool.start", actor, tool, key=key, status=new, resumed=True)
                    elif new == "completed":
                        emit("tool.end", actor, tool, key=key, status=new)
                    elif new == "failed":
                        emit("error", actor, tool, key=key, status=new, error=after.get("error"))
                    elif new == "canceled":
                        emit("tool.end", actor, tool, key=key, status=new)
            elif "Session" in labels and op == "u" and not before.get("closedAt") and after.get("closedAt"):
                emit("idle", agent_of_session(_key(ev, "Session", "triggerMsgId")), None, session=after.get("id"))
            elif "Chain" in labels and op == "u" and before.get("status") == "active" and after.get("status") == "suspended":
                actor = (e["metadata"].get("txMetadata") or {}).get("agentId")
                emit("error", actor, after.get("id"), chainId=after.get("id"), reason=after.get("suspendReason"))
            elif "Agent" in labels and op == "u" and not before.get("quarantined") and after.get("quarantined"):
                emit("error", (e["metadata"].get("txMetadata") or {}).get("agentId"), after.get("id"), reason="quarantine")
        elif ev["eventType"] == "r" and op == "c":
            if ev["type"] == "VOTED":
                p = _props(ev, "after")
                emit("vote", _key(ev["start"], "Agent", "id"), _key(ev["end"], "Approval", "id"),
                     decision=p.get("decision"), onBehalfOf=p.get("onBehalfOf"))
            elif ev["type"] == "RECEIVED":
                received.append({"inbox": _key(ev["start"], "InboxDay", "inboxId"), "messageId": _key(ev["end"], "Message", "id"), "t": t})
    return out, received


def kg_changes(events: list[dict]) -> list[dict]:
    """Changements d'une transaction de KG, avec les identifiants d'entité (clé de nœud `Entity.id`)."""
    out = []
    for e in events:
        ev = e["event"]
        if ev["eventType"] == "n":
            ent = _key(ev, "Entity", "id")
            out.append({"eventId": e["id"], "kind": "node", "op": ev["operation"], "labels": ev["labels"], "entityId": ent})
        else:
            out.append({"eventId": e["id"], "kind": "rel", "op": ev["operation"], "type": ev["type"],
                        "from": _key(ev["start"], "Entity", "id"), "to": _key(ev["end"], "Entity", "id")})
    return out
