import pytest

from orchestra.runtime.cpa import critical_path, simulate_delay
from orchestra.seed import kg_data as K

T = lambda i, d, *deps: {"id": i, "durationDays": d, "dependsOn": list(deps)}
#   A(3) -> B(2) -> D(4)        chemin critique A-B-D = 9 jours
#   A(3) -> C(1) -> D           C a 1 jour de marge
DIAMOND = [T("A", 3), T("B", 2, "A"), T("C", 1, "A"), T("D", 4, "B", "C")]


def test_forward_backward_pass_and_critical_path():
    r = critical_path(DIAMOND)
    assert r["projectDays"] == 9
    assert r["tasks"]["A"] == {"es": 0, "ef": 3, "ls": 0, "lf": 3, "slack": 0}
    assert r["tasks"]["C"] == {"es": 3, "ef": 4, "ls": 4, "lf": 5, "slack": 1}
    assert r["criticalPath"] == ["A", "B", "D"]


def test_delay_on_critical_task_delays_the_project():
    r = simulate_delay(DIAMOND, "B", 5)
    assert r["taskWasCritical"] and r["projectDelayDays"] == 5 and r["newProjectDays"] == 14
    assert r["shiftedTasks"] == {"D": 5}


def test_delay_absorbed_by_slack():
    r = simulate_delay(DIAMOND, "C", 1)
    assert not r["taskWasCritical"] and r["projectDelayDays"] == 0 and r["slackAbsorbed"] == 1
    r = simulate_delay(DIAMOND, "C", 4)
    assert r["projectDelayDays"] == 3 and r["criticalPath"] == ["A", "C", "D"]


def test_cycle_and_unknown_task_are_rejected():
    with pytest.raises(ValueError):
        critical_path([T("A", 1, "B"), T("B", 1, "A")])
    with pytest.raises(KeyError):
        simulate_delay(DIAMOND, "Z", 1)


def test_synthetic_project_is_consistent_with_its_own_forward_pass():
    p = K.generate_kg_produit()
    proj = K.generate_kg_projet(p["tests"], [x["id"] for x in p["parts"] if x["level"] == 1])
    deps = {t["id"]: [] for t in proj["tasks"]}
    for d in proj["depends"]:
        deps[d["from"]].append(d["to"])
    tasks = [{"id": t["id"], "durationDays": t["durationDays"], "dependsOn": deps[t["id"]]} for t in proj["tasks"]]
    r = critical_path(tasks)
    assert all(r["tasks"][t["id"]]["es"] == t["plannedStartDay"] for t in proj["tasks"])   # le seed est cohérent avec la CPA
    assert r["criticalPath"] and r["projectDays"] > 0
