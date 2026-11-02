"""Données synthétiques déterministes (graine fixe). Produit fictif : station de pompage modulaire SPM-7."""
import random
from datetime import date, timedelta

SEED = 42
PROJECT_START = date(2026, 1, 5)

FAMILIES = {
    "Hydraulique": ["Pompe", "Vanne", "Clapet", "Joint", "Tuyauterie", "Filtre", "Bride", "Raccord"],
    "Électrique": ["Moteur", "Variateur", "Capteur", "Contacteur", "Câble", "Relais", "Alimentation"],
    "Mécanique": ["Palier", "Arbre", "Accouplement", "Roulement", "Support", "Carter", "Vis"],
    "Contrôle": ["Automate", "Sonde", "Afficheur", "Passerelle", "Carte E/S", "Module radio"],
    "Structure": ["Châssis", "Panneau", "Charnière", "Platine", "Cadre", "Traverse"],
    "Fluidique": ["Réservoir", "Buse", "Diffuseur", "Collecteur", "Soupape", "Purgeur"],
}
SUBASSEMBLIES = ["Groupe motopompe", "Armoire de commande", "Circuit hydraulique", "Châssis et carrosserie", "Instrumentation", "Réservoir et collecteurs"]
TEST_KINDS = ["pression", "vibration", "fatigue", "étanchéité", "thermique", "CEM", "endurance"]
TASK_PHASES = {
    "Conception": ["Cahier des charges détaillé", "Revue de conception préliminaire", "Conception du groupe motopompe", "Conception de l'armoire", "Plans du châssis", "Revue de conception critique"],
    "Prototype": ["Approvisionnement prototype", "Assemblage prototype", "Câblage et paramétrage", "Mise en service banc", "Premier démarrage"],
    "Essais": ["Essais de pression", "Essais de vibration", "Essais d'étanchéité", "Essais thermiques", "Essais CEM", "Essais d'endurance", "Analyse des résultats d'essais"],
    "Industrialisation": ["Dossier de fabrication", "Outillage", "Série pilote", "Qualification du procédé", "Formation atelier"],
    "Livraison": ["Préparation documentaire", "Pré-série client", "Recette client", "Revue de fin de projet", "Transfert au service après-vente", "Clôture du projet", "Retour d'expérience"],
}
ROLES = ["Ingénieur hydraulique", "Ingénieur électricien", "Mécanicien d'essais", "Technicien banc", "Automaticien", "Qualiticien", "Chef d'atelier", "Dessinateur"]


def generate_kg_produit(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    parts, contains = [], []
    pid = lambda n: f"PRT-{n:04d}"
    n = 1
    parts.append({"id": pid(n), "name": "Station de pompage modulaire SPM-7", "level": 0, "family": "Produit", "revision": "A", "criticality": 5})
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
            parts.append({"id": pid(n), "name": f"Ensemble {rng.choice(FAMILIES[fam]).lower()} {SUBASSEMBLIES[i].split()[0].lower()} {j + 1}", "level": 2, "family": fam, "revision": "A", "criticality": rng.randint(2, 5)})
            l2.append(pid(n)); contains.append({"from": parent, "to": pid(n), "qty": 1})
    n_l3 = 200 - len(parts)
    l3 = []
    for k in range(n_l3):
        n += 1
        fam = fam_names[rng.randrange(len(fam_names))]
        parts.append({"id": pid(n), "name": f"{rng.choice(FAMILIES[fam])} {fam.lower()} réf. {rng.randint(100, 999)}", "level": 3, "family": fam, "revision": rng.choice("AAAB"), "criticality": rng.randint(1, 5)})
        l3.append(pid(n))
        parent = l2[k % len(l2)] if k < 3 * len(l2) else rng.choice(l2)
        contains.append({"from": parent, "to": pid(n), "qty": rng.randint(1, 8)})
    # pièces partagées : second parent différent
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
        tests.append({"id": tid, "name": f"Essai de {kind} n°{t}", "kind": kind, "durationDays": rng.randint(1, 10), "status": "passed"})
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
        if t["phase"] == "Essais":
            kinds = [k for k in TEST_KINDS if k.lower() in t["name"].lower()]
            if kinds:  # lien métier par clé (pas de relation entre bases)
                t["testRefs"] = [x["id"] for x in tests if x["kind"] == kinds[0]]
    conception = [t for t in tasks if t["phase"] == "Conception"]
    for t, pid in zip(conception, l1_ids):
        t["partRef"] = pid
    # passe avant pour dates planifiées
    by_id = {t["id"]: t for t in tasks}
    preds = {t["id"]: [d["to"] for d in deps if d["from"] == t["id"]] for t in tasks}
    for t in tasks:
        start = max([by_id[p]["plannedStartDay"] + by_id[p]["durationDays"] for p in preds[t["id"]]], default=0)
        t["plannedStartDay"] = start
        t["plannedStart"] = (PROJECT_START + timedelta(days=start)).isoformat()
        t["status"] = "planned"
    resources = [{"id": f"RES-{i + 1}", "name": f"Ressource {i + 1}", "role": ROLES[i], "capacity": 1.0} for i in range(len(ROLES))]
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
        """Comme la requête `part_tests` : essais qui couvrent la pièce ou un ensemble qui la contient."""
        return set(direct.get(x, ())) | {t for a in ancestors(x) for t in direct.get(a, ())}

    def candidates(x):
        """Comme la requête `replacement_candidates` : même niveau et même famille, par criticité puis identifiant."""
        return sorted((y for y, q in parts.items() if q["level"] == parts[x]["level"] and q["family"] == parts[x]["family"] and y != x),
                      key=lambda y: (parts[y]["criticality"], y))
    return parts, parents, tests_of, candidates


def loop_parts(produit: dict) -> list[str]:
    """Pièces qui provoquent la boucle légitime Ingénierie ↔ Essais : la pièce est couverte et partagée, son premier
    candidat de remplacement n'est couvert par aucun essai (Essais le refuse), le deuxième l'est (Essais l'accepte)."""
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
    assert loop, "aucune pièce ne provoque la boucle Ingénierie ↔ Essais : revoir la génération des essais"
    shared = [p for p in shared if p != loop[0]]
    others = sorted(p["id"] for p in produit["parts"] if p["level"] == 3 and p["id"] not in shared and p != loop[0])
    chosen = [loop[0]] + shared[:2] + rng.sample(others, 7)       # INC-001 : l'incident du scénario (avec boucle légitime)
    templates = [
        ("Fuite constatée sur {n} après {h} h de fonctionnement", "majeure"),
        ("Vibration anormale mesurée sur {n} à {h} h de service", "majeure"),
        ("Défaillance prématurée de {n} chez le client", "critique"),
        ("Échauffement excessif de {n} pendant la recette", "mineure"),
        ("Corrosion visible sur {n} après {h} h", "mineure"),
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
