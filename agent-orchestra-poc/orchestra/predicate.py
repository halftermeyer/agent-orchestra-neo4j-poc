"""Prédicats structurés de routage (jamais de Cypher libre).

Grammaire : {"field", "op", "value"} | {"all": [...]} | {"any": [...]} | {"not": p}
`field` : chemin pointé dans le payload du message, ou `msg.from` / `msg.performative` / `msg.chainId`.
"""
from typing import Any

LEAF_OPS = {"eq", "ne", "in", "nin", "contains", "prefix", "exists", "gt", "gte", "lt", "lte"}
MSG_FIELDS = {"from", "performative", "chainId", "conversationId"}
MAX_DEPTH = 5


def validate(p: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH or not isinstance(p, dict):
        raise ValueError("invalid predicate")
    if "all" in p or "any" in p:
        key = "all" if "all" in p else "any"
        if set(p) != {key} or not isinstance(p[key], list) or not p[key]:
            raise ValueError("all/any: a non-empty list is expected")
        for q in p[key]:
            validate(q, depth + 1)
    elif "not" in p:
        if set(p) != {"not"}:
            raise ValueError("not: a single key is expected")
        validate(p["not"], depth + 1)
    else:
        if set(p) - {"field", "op", "value"} or "field" not in p or p.get("op") not in LEAF_OPS:
            raise ValueError(f"invalid leaf (ops: {sorted(LEAF_OPS)})")
        if not isinstance(p["field"], str) or not p["field"]:
            raise ValueError("invalid field")
        if p["op"] in ("in", "nin") and not isinstance(p.get("value"), list):
            raise ValueError("in/nin: a list is expected")


def _get(field: str, payload: dict, msg: dict):
    if field.startswith("msg."):
        return msg.get(field[4:])
    cur: Any = payload
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def evaluate(p: dict, payload: dict | None, msg: dict) -> bool:
    payload = payload or {}
    if "all" in p:
        return all(evaluate(q, payload, msg) for q in p["all"])
    if "any" in p:
        return any(evaluate(q, payload, msg) for q in p["any"])
    if "not" in p:
        return not evaluate(p["not"], payload, msg)
    v, op, want = _get(p["field"], payload, msg), p["op"], p.get("value")
    if op == "exists":
        return (v is not None) == bool(want if want is not None else True)
    if v is None:
        return op in ("ne", "nin")
    try:
        return {
            "eq": lambda: v == want, "ne": lambda: v != want,
            "in": lambda: v in want, "nin": lambda: v not in want,
            "contains": lambda: want in v, "prefix": lambda: str(v).startswith(str(want)),
            "gt": lambda: v > want, "gte": lambda: v >= want, "lt": lambda: v < want, "lte": lambda: v <= want,
        }[op]()
    except TypeError:
        return False
