"""Méthode du chemin critique (CPA) : passe avant, passe arrière, marges, simulation d'un retard."""
from collections import defaultdict, deque


def critical_path(tasks: list[dict]) -> dict:
    """tasks : [{id, name?, durationDays, dependsOn: [ids]}]. Retourne ES/EF/LS/LF/marge par tâche et le chemin critique."""
    by_id = {t["id"]: t for t in tasks}
    succ, indeg = defaultdict(list), {t["id"]: 0 for t in tasks}
    for t in tasks:
        for d in t.get("dependsOn", []):
            if d in by_id:
                succ[d].append(t["id"])
                indeg[t["id"]] += 1
    order, q = [], deque(sorted(i for i, n in indeg.items() if n == 0))
    while q:
        i = q.popleft()
        order.append(i)
        for s in sorted(succ[i]):
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(order) != len(tasks):
        raise ValueError("cycle in the schedule dependencies")
    es, ef = {}, {}
    for i in order:                                              # passe avant
        es[i] = max((ef[d] for d in by_id[i].get("dependsOn", []) if d in by_id), default=0)
        ef[i] = es[i] + by_id[i]["durationDays"]
    end = max(ef.values(), default=0)
    ls, lf = {}, {}
    for i in reversed(order):                                    # passe arrière
        lf[i] = min((ls[s] for s in succ[i]), default=end)
        ls[i] = lf[i] - by_id[i]["durationDays"]
    info = {i: {"es": es[i], "ef": ef[i], "ls": ls[i], "lf": lf[i], "slack": ls[i] - es[i]} for i in order}
    crit = [i for i in order if info[i]["slack"] == 0]
    path, cur = [], next((i for i in crit if es[i] == 0), None)  # un chemin critique, de gauche à droite
    while cur:
        path.append(cur)
        cur = next((s for s in sorted(succ[cur]) if info[s]["slack"] == 0 and es[s] == ef[cur]), None)
    return {"projectDays": end, "tasks": info, "criticalPath": path}


def simulate_delay(tasks: list[dict], task_id: str, delay_days: int) -> dict:
    base = critical_path(tasks)
    if task_id not in base["tasks"]:
        raise KeyError(task_id)
    bumped = [dict(t, durationDays=t["durationDays"] + (delay_days if t["id"] == task_id else 0)) for t in tasks]
    new = critical_path(bumped)
    moved = {i: new["tasks"][i]["es"] - base["tasks"][i]["es"] for i in new["tasks"] if new["tasks"][i]["es"] != base["tasks"][i]["es"]}
    slack = base["tasks"][task_id]["slack"]
    return {"taskId": task_id, "delayDays": delay_days, "taskWasCritical": slack == 0, "slackBefore": slack,
            "slackAbsorbed": min(slack, delay_days), "baseProjectDays": base["projectDays"], "newProjectDays": new["projectDays"],
            "projectDelayDays": new["projectDays"] - base["projectDays"], "shiftedTasks": dict(sorted(moved.items())),
            "criticalPath": new["criticalPath"]}
