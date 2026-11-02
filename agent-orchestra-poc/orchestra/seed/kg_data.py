"""Deterministic synthetic data (fixed seed). Fictional product: modular pumping station SPM-7."""
import random
from datetime import date, timedelta

SEED = 42
PROJECT_START = date(2026, 1, 5)

FAMILIES = {
    "Hydraulic": ["Pump", "Valve", "Check valve", "Seal", "Piping", "Filter", "Flange", "Fitting"],
    "Electrical": ["Motor", "Drive", "Sensor", "Contactor", "Cable", "Relay", "Power supply"],
    "Mechanical": ["Bearing", "Shaft", "Coupling", "Roller bearing", "Bracket", "Housing", "Screw"],
    "Control": ["PLC", "Probe", "Display", "Gateway", "I/O card", "Radio module"],
    "Structural": ["Frame", "Panel", "Hinge", "Base plate", "Chassis", "Crossbeam"],
    "Fluidic": ["Tank", "Nozzle", "Diffuser", "Manifold", "Relief valve", "Drain"],
}
SUBASSEMBLIES = ["Motor-pump unit", "Control cabinet", "Hydraulic circuit", "Frame and body", "Instrumentation", "Tank and manifolds"]
TEST_KINDS = ["pressure", "vibration", "fatigue", "leak-tightness", "thermal", "EMC", "endurance"]
TASK_PHASES = {
    "Design": ["Detailed requirements", "Preliminary design review", "Motor-pump unit design", "Cabinet design", "Frame drawings", "Critical design review"],
    "Prototype": ["Prototype procurement", "Prototype assembly", "Wiring and configuration", "Bench commissioning", "First start-up"],
    "Testing": ["Pressure tests", "Vibration tests", "Leak-tightness tests", "Thermal tests", "EMC tests", "Endurance tests", "Test results analysis"],
    "Industrialisation": ["Manufacturing file", "Tooling", "Pilot series", "Process qualification", "Workshop training"],
    "Delivery": ["Documentation package", "Customer pre-series", "Customer acceptance", "Project closing review", "Handover to after-sales", "Project closure", "Lessons learned"],
}
ROLES = ["Hydraulics engineer", "Electrical engineer", "Test mechanic", "Bench technician", "Control engineer", "Quality engineer", "Workshop manager", "Draughtsman"]


def generate_kg_produit(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    parts, contains = [], []
    pid = lambda n: f"PRT-{n:04d}"
    n = 1
    parts.append({"id": pid(n), "name": "Modular pumping station SPM-7", "level": 0, "family": "Produit", "revision": "A", "criticality": 5})
    root = pid(n)
    l1 = []
    for name in SUBASSEMBLIES:
        n += 1
        parts.append({"id": pid(n), "name": name, "level": 1, "family": "Assemblage", "revision": "A", "criticality": rng.randint(3, 5)})
        l1.append(pid(n)); contains.append({"from": root, "to": pid(n), "qty": 1})
    l2 = []
    fam_names = list(FAMILIES)
    for i, parent in enumerate(l1):
        for j in range(5):
            n += 1
            fam = fam_names[(i + j) % len(fam_names)]
            parts.append({"id": pid(n), "name": f"{fam} {rng.choice(FAMILIES[fam]).lower()} assembly {j + 1} ({SUBASSEMBLIES[i].lower()})", "level": 2, "family": fam, "revision": "A", "criticality": rng.randint(2, 5)})
            l2.append(pid(n)); contains.append({"from": parent, "to": pid(n), "qty": 1})
    n_l3 = 200 - len(parts)
    l3 = []
    for k in range(n_l3):
        n += 1
        fam = fam_names[rng.randrange(len(fam_names))]
        parts.append({"id": pid(n), "name": f"{fam} {rng.choice(FAMILIES[fam]).lower()} ref. {rng.randint(100, 999)}", "level": 3, "family": fam, "revision": rng.choice("AAAB"), "criticality": rng.randint(1, 5)})
        l3.append(pid(n))
        parent = l2[k % len(l2)] if k < 3 * len(l2) else rng.choice(l2)
        contains.append({"from": parent, "to": pid(n), "qty": rng.randint(1, 8)})
    # shared parts: different second parent
    seen = {(c["from"], c["to"]) for c in contains}
    for part in rng.sample(l3, 40):
        parent = rng.choice(l2)
        if (parent, part) not in seen:
            seen.add((parent, part)); contains.append({"from": parent, "to": part, "qty": rng.randint(1, 4)})
    tests, covers = [], []
    coverable = l2 + l3
    covered_targets = rng.sample(l3, int(len(l3) * 0.7))
    for t in range(1, 51):
        kind = TEST_KINDS[(t - 1) % len(TEST_KINDS)]
        tid = f"TST-{t:03d}"
        tests.append({"id": tid, "name": f"{kind.capitalize()} test no. {t}", "kind": kind, "durationDays": rng.randint(1, 10), "status": "passed"})
        pool = covered_targets if t <= 40 else coverable
        for target in rng.sample(pool, rng.randint(1, 5)):
            covers.append({"from": tid, "to": target})
    covers = [dict(t) for t in {tuple(sorted(c.items())) for c in covers}]
    covers.sort(key=lambda c: (c["from"], c["to"]))
    version = {"id": "VER-1.0", "label": "v1.0", "releasedAt": "2025-11-03", "current": True}
    return {"parts": parts, "contains": contains, "tests": tests, "covers": covers, "versions": [version]}


def generate_kg_projet(tests: list[dict], l1_ids: list[str], seed: int = SEED) -> dict:
    rng = random.Random(seed + 1)
    tasks, deps = [], []
    n = 0
    for phase, names in TASK_PHASES.items():
        for name in names:
            n += 1
            tasks.append({"id": f"TSK-{n:02d}", "name": name, "phase": phase, "durationDays": rng.randint(3, 15)})
    tasks = tasks[:30]
    for i, t in enumerate(tasks):
        if i == 0:
            continue
        for p in rng.sample(range(max(0, i - 4), i), min(i, rng.randint(1, 2))):
            deps.append({"from": t["id"], "to": tasks[p]["id"]})  # from DEPENDS_ON to
    for t in tasks:
        if t["phase"] == "Testing":
            kinds = [k for k in TEST_KINDS if k.lower() in t["name"].lower()]
            if kinds:  # business link by key (no relationship across databases)
                t["testRefs"] = [x["id"] for x in tests if x["kind"] == kinds[0]]
    conception = [t for t in tasks if t["phase"] == "Conception"]
    for t, pid in zip(conception, l1_ids):
        t["partRef"] = pid
    # forward pass for scheduled dates
    by_id = {t["id"]: t for t in tasks}
    preds = {t["id"]: [d["to"] for d in deps if d["from"] == t["id"]] for t in tasks}
    for t in tasks:
        start = max([by_id[p]["plannedStartDay"] + by_id[p]["durationDays"] for p in preds[t["id"]]], default=0)
        t["plannedStartDay"] = start
        t["plannedStart"] = (PROJECT_START + timedelta(days=start)).isoformat()
        t["status"] = "planned"
    resources = [{"id": f"RES-{i + 1}", "name": f"Resource {i + 1}", "role": ROLES[i], "capacity": 1.0} for i in range(len(ROLES))]
    assigned = [{"from": t["id"], "to": rng.choice(resources)["id"]} for t in tasks]
    return {"tasks": tasks, "depends": deps, "resources": resources, "assigned": assigned}


def _bom_index(produit: dict):
    parts = {x["id"]: x for x in produit["parts"]}
    parents: dict[str, set] = {}
    for c in produit["contains"]:
        parents.setdefault(c["to"], set()).add(c["from"])
    direct: dict[str, set] = {}
    for c in produit["covers"]:
        direct.setdefault(c["to"], set()).add(c["from"])

    def ancestors(x, seen=None):
        seen = seen if seen is not None else set()
        for a in parents.get(x, ()):
            if a not in seen:
                seen.add(a)
                ancestors(a, seen)
        return seen

    def tests_of(x):
        """Like the `part_tests` query: tests that cover the part or an assembly containing it."""
        return set(direct.get(x, ())) | {t for a in ancestors(x) for t in direct.get(a, ())}

    def candidates(x):
        """Like the `replacement_candidates` query: same level and same family, by criticality then identifier."""
        return sorted((y for y, q in parts.items() if q["level"] == parts[x]["level"] and q["family"] == parts[x]["family"] and y != x),
                      key=lambda y: (parts[y]["criticality"], y))
    return parts, parents, tests_of, candidates


def loop_parts(produit: dict) -> list[str]:
    """Parts that trigger the legitimate Engineering ↔ Testing loop: the part is covered and shared, its first
    replacement candidate is covered by no test (Testing refuses it), the second is (Testing accepts it)."""
    parts, parents, tests_of, candidates = _bom_index(produit)
    out = []
    for x in sorted(parts):
        if parts[x]["level"] != 3 or len(parents.get(x, ())) < 2 or not tests_of(x):
            continue
        c = candidates(x)
        if len(c) >= 2 and not tests_of(c[0]) and tests_of(c[1]):
            out.append(x)
    return out


def generate_incidents(produit: dict, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed + 2)
    by_id = {p["id"]: p for p in produit["parts"]}
    parents = {}
    for c in produit["contains"]:
        parents.setdefault(c["to"], set()).add(c["from"])
    covered = {c["to"] for c in produit["covers"]}
    shared = sorted(p for p, ps in parents.items() if len(ps) > 1 and by_id[p]["level"] == 3 and p in covered)
    loop = loop_parts(produit)
    assert loop, "no part triggers the Engineering ↔ Testing loop: review test generation"
    shared = [p for p in shared if p != loop[0]]
    others = sorted(p["id"] for p in produit["parts"] if p["level"] == 3 and p["id"] not in shared and p != loop[0])
    chosen = [loop[0]] + shared[:2] + rng.sample(others, 7)       # INC-001 : the scenario incident (with legitimate loop)
    templates = [
        ("Leak found on {n} after {h} h of operation", "major"),
        ("Abnormal vibration measured on {n} at {h} h of service", "major"),
        ("Premature failure of {n} at the customer", "critical"),
        ("Excessive heating of {n} during acceptance", "minor"),
        ("Visible corrosion on {n} after {h} h", "minor"),
    ]
    start = date(2026, 3, 2)
    out = []
    for i, comp in enumerate(chosen):
        tpl, sev = templates[i % len(templates)] if i else templates[2]
        out.append({
            "id": f"INC-{i + 1:03d}", "kind": "incident", "componentId": comp, "severity": sev,
            "description": tpl.format(n=by_id[comp]["name"], h=rng.randint(40, 900)),
            "observedAt": (start + timedelta(days=i * 3)).isoformat(),
        })
    return out
