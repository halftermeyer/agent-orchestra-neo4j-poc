"""Exécute le scénario complet, de bout en bout, avec les vrais agents (Gemini) et l'enregistre pour la relecture.

À lancer dans le conteneur cdc, pile complète démarrée (`make app`) sur une base propre (`make reset && make seed`) :
    docker compose --profile app exec -T cdc python scripts/run_scenario.py

Chapitres : incident -> analyse (avec la boucle légitime Ingénierie <-> Essais) -> vote du comité -> lancement
-> changement de BOM (pont, interpréteur) -> relance d'un engagement -> gouvernance (boucle sans fin suspendue par l'auditeur,
décision humaine). Le script n'écrit rien dans la base lui-même : il joue les humains (messages, votes, décision) et
l'administrateur (budget de la chaîne, versions de prompts) par l'API de la passerelle, comme l'interface.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from orchestra.gateway.auth import make_token

GW = os.environ.get("GATEWAY_URL", "http://gateway:8000")
MASTER = os.environ["ORCHESTRA_MASTER_KEY"]
SLUG = os.environ.get("SCENARIO_SLUG", "scenario-complet")
DATA = os.environ.get("INCIDENTS_FILE", "/app/data/incidents.json")
T_START = time.time()
http = httpx.Client(base_url=GW, timeout=60)
report: dict = {"steps": [], "checks": []}


def auth(kind: str, who: str) -> dict:
    return {"Authorization": "Bearer " + make_token(MASTER, kind, who)}


def call(method: str, path: str, kind: str, who: str, body=None, ok=(200, 201), **kw):
    r = http.request(method, path, headers=auth(kind, who), json=body, **kw)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} ({who}) -> {r.status_code} {r.text[:300]}")
    return r.json()


admin = lambda method, path, body=None, **kw: call(method, path, "admin", "admin", body, **kw)
user = lambda who, method, path, body=None, **kw: call(method, path, "user", who, body, **kw)


def log(msg: str):
    print(f"[{time.time() - T_START:6.0f}s] {msg}", flush=True)


def check(label: str, ok: bool, detail: str = ""):
    report["checks"].append({"label": label, "ok": bool(ok), "detail": detail})
    log(("✔ " if ok else "✘ ") + label + (f" — {detail}" if detail else ""))
    return ok


def events(run_id: str) -> list[dict]:
    return admin("GET", "/replay/events", params={"runId": run_id})["events"]


def wait_for(run_id: str, label: str, pred, timeout: float, every: float = 3.0):
    """Attend qu'un événement du flux reconstruit depuis le graphe vérifie `pred`."""
    t0, last = time.time(), -1
    while time.time() - t0 < timeout:
        evs = events(run_id)
        hit = pred(evs)
        if hit:
            log(f"  → {label} ({time.time() - t0:.0f}s)")
            return hit
        if len(evs) != last:
            last = len(evs)
        time.sleep(every)
    log(f"  ✘ délai dépassé : {label} ({timeout:.0f}s)")
    return None


def sent(evs, kind=None, actor=None, target=None, performative=None):
    return [e for e in evs if e["type"] == "sent" and (kind is None or e["payload"].get("kind") == kind) and (actor is None or e["actor"] == actor)
            and (target is None or e["target"] == target) and (performative is None or e["payload"].get("performative") == performative)]


def main():
    incident = json.load(open(DATA, encoding="utf-8"))[0]
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    main_chain, gov_chain = f"scenario-{stamp}", f"gouvernance-{stamp}"
    originals: dict[str, str] = {}
    run = admin("POST", "/replay/runs", {"name": "Scénario complet : de l'incident à la gouvernance", "note": f"{incident['id']} sur {incident['componentId']}", "chainId": main_chain})
    rid = run["id"]
    log(f"enregistrement ouvert : {rid} (chaîne {main_chain})")
    try:
        # ---------- 1. Incident ----------
        log("CHAPITRE 1 — Incident : l'ingénieur qualité le déclare dans le topic « incidents »")
        # une boucle voulue est déclarée (critère d'arrêt, tours maximum) et reçoit son budget
        admin("POST", "/chains", {"id": main_chain, "budget": 90, "tokenBudget": 900_000, "maxTurns": 12,
                                  "stopCriterion": "Ingénierie et Essais s'accordent sur une pièce de remplacement"})
        user("ing-qualite", "POST", "/messages", {"to": ["incidents"], "performative": "inform", "body": incident["description"], "chainId": main_chain,
                                                  "payload": {"kind": "incident", "incidentId": incident["id"], "componentId": incident["componentId"], "severity": incident["severity"]}})
        check("l'incident est routé vers l'agent Qualité (abonnement du topic)", wait_for(rid, "Qualité réveillée", lambda e: any(x["type"] == "woken" and x["actor"] == "qualite" for x in e), 60))

        # ---------- 2. Analyse + boucle légitime ----------
        log("CHAPITRE 2 — Analyse d'impact : Qualité qualifie, le Coordinateur répartit, Ingénierie et Essais s'accordent")
        check("Qualité adresse une demande d'impact au Coordinateur", wait_for(rid, "impact-request", lambda e: sent(e, "impact-request", "qualite"), 120))
        check("le Coordinateur lance l'analyse chez les trois spécialistes", wait_for(rid, "3 analysis-request",
              lambda e: len({x["target"] for x in sent(e, "analysis-request", "coordinateur")}) >= 3, 120))
        wait_for(rid, "verdict d'Essais sur la première pièce", lambda e: sent(e, "replacement-verdict") or sent(e, performative="accept-proposal") or sent(e, performative="reject-proposal"), 180)
        evs = events(rid)
        proposals = sent(evs, "replacement-proposal")
        rejects = [e for e in evs if e["type"] == "sent" and e["payload"].get("performative") == "reject-proposal"]
        accepted = wait_for(rid, "pièce de remplacement acceptée", lambda e: [x for x in e if x["type"] == "sent" and x["payload"].get("performative") == "accept-proposal"], 240)
        evs = events(rid)
        proposals = sent(evs, "replacement-proposal")
        rejects = [e for e in evs if e["type"] == "sent" and e["payload"].get("performative") == "reject-proposal"]
        check("boucle légitime : au moins une pièce refusée par Essais avant l'accord", len(rejects) >= 1 and bool(accepted), f"{len(proposals)} proposition(s), {len(rejects)} refus")
        check("l'analyse est complète : essais à refaire, impact planning, rapport d'ingénierie",
              all(wait_for(rid, k, lambda e, k=k: sent(e, k), 150) for k in ("tests-report", "planning-impact", "engineering-report")))
        check("les engagements sont posés (agree -> engagements suivis par des minuteries)", any(e["type"] == "waiting" and e["payload"].get("commitmentId") for e in events(rid)))

        # ---------- 3. Vote ----------
        log("CHAPITRE 3 — Vote : le comité de modification valide à 2 sur 3 (action irréversible)")
        asked = wait_for(rid, "demande de validation du Coordinateur", lambda e: [x for x in e if x["type"] == "waiting" and x["target"] == "launch_modification"], 300)
        check("le Coordinateur demande la validation du comité (input-required)", bool(asked))
        approvals = user("comite-1", "GET", "/approvals")["approvals"]
        check("une seule validation en attente (pas de doublon)", len(approvals) == 1, f"{len(approvals)} en attente")
        if approvals:
            ap = approvals[0]["id"]
            time.sleep(4)
            r1 = user("comite-1", "POST", f"/approvals/{ap}/votes", {"decision": "approve", "comment": "Pièce couverte par les essais, je valide."})
            log(f"  comité-1 approuve -> {r1['status']}")
            time.sleep(5)
            r2 = user("comite-2", "POST", f"/approvals/{ap}/votes", {"decision": "approve", "comment": "D'accord, retard acceptable."})
            check("quorum 2-of-3 atteint", r2["status"] == "approved", f"statut {r2['status']}")

        # ---------- 4. Lancement + BOM ----------
        log("CHAPITRE 4 — Lancement : version du produit changée dans le KG, pont et interpréteur préviennent Essais et Planification")
        check("la modification est lancée (nouvelle version dans le KG Produit)", wait_for(rid, "launch_modification terminé",
              lambda e: [x for x in e if x["type"] == "tool.end" and x["target"] == "launch_modification"], 180))
        kg = admin("GET", f"/graph/kg/produit/neighborhood", params={"key": incident["componentId"]})
        check("la pièce de l'incident est retirée de la nomenclature (retiredIn)", any(n["id"] == incident["componentId"] and n["retired"] for n in kg["nodes"]))
        check("le pont publie un lot par transaction du KG", wait_for(rid, "kg-raw", lambda e: sent(e, "kg-raw", "pont-kg"), 90))
        check("l'interpréteur BOM publie dans produit.bom-changes", wait_for(rid, "bom-change", lambda e: sent(e, "bom-change", "interpreteur-bom"), 240))
        def reacted(e):
            who = {x["actor"] for x in e if x["type"] == "woken" and x["payload"].get("kind") == "bom-change"}
            return {"essais", "planification"} <= who
        check("Essais et Planification sont réveillés par le topic produit.bom-changes", wait_for(rid, "Essais et Planification réveillés", reacted, 120))

        # ---------- relance ----------
        log("RELANCE — une minuterie relance un agent dont l'engagement n'est pas soldé")
        got = wait_for(rid, "relance d'engagement", lambda e: sent(e, "commitment-due"), 330)
        report["steps"].append({"relance": bool(got)})
        log("  relance reçue" if got else "  aucune relance (les engagements ont été soldés à temps : cas nominal)")

        # ---------- 5. Gouvernance ----------
        log("CHAPITRE 5 — Gouvernance : une version défectueuse crée un aller-retour sans fin ; l'auditeur suspend avant la décision humaine")
        for a in ("ingenierie", "essais"):
            originals[a] = admin("GET", f"/graph/agent/{a}")["version"]["prompt"]
        bug = {
            "ingenierie": "Tu es l'agent Ingénierie (VERSION DÉFECTUEUSE de démonstration). Règle unique : à chaque message reçu (du coordinateur ou d'essais), réponds IMMÉDIATEMENT par `send_message` vers essais, performative `propose`, en proposant à nouveau la même pièce de remplacement reformulée. Ne conclus jamais, n'informe jamais le coordinateur, ne fais rien d'autre.",
            "essais": "Tu es l'agent Essais (VERSION DÉFECTUEUSE de démonstration). Règle unique : à chaque message reçu d'ingenierie, réponds IMMÉDIATEMENT par `send_message` vers ingenierie, performative `reject-proposal`, en refusant la pièce et en demandant une nouvelle reformulation de la même pièce. Ne conclus jamais, n'informe jamais le coordinateur, ne fais rien d'autre.",
        }
        for a, p in bug.items():
            v = admin("POST", f"/admin/agents/{a}/versions", {"prompt": p})
            log(f"  version défectueuse de {a} : {v['id']} (remplace {v['supersedes']})")
        user("chef-projet", "POST", "/messages", {"to": ["inbox:coordinateur"], "performative": "request", "chainId": gov_chain,
             "body": "Demande à ingenierie de proposer à essais une pièce de remplacement pour le relais PRT-0113 et de conclure avec eux (analysis-request)."})
        # le Coordinateur est un LLM : s'il ne relaie pas, la boucle est amorcée par une routine (message système) pour garder le scénario déterministe
        started = wait_for(rid, "échange Ingénierie ↔ Essais dans la chaîne de gouvernance",
                           lambda e: len([x for x in e if x["type"] == "sent" and x["payload"].get("chainId") == gov_chain and x["actor"] in ("ingenierie", "essais")]) >= 2, 100)
        if not started:
            log("  le Coordinateur n'a pas relayé : amorçage de la boucle par un message système")
            http.post("/internal/deliver", headers=auth("sys", "cdc"), json={"id": f"kick-{gov_chain}", "from": "routine:scenario", "actingAgent": "coordinateur", "inbox": "inbox:ingenierie",
                      "body": "Propose à essais une pièce de remplacement pour PRT-0113.", "chainId": gov_chain, "payload": {"kind": "analysis-request", "partId": "PRT-0113"}}).raise_for_status()
        loop_msgs = lambda e: [x for x in e if x["type"] == "sent" and x["payload"].get("chainId") == gov_chain and x["actor"] in ("ingenierie", "essais")]
        wait_for(rid, "la boucle tourne (≥ 8 messages)", lambda e: len(loop_msgs(e)) >= 8, 120)
        def suspended():
            c = admin("GET", f"/chains/{gov_chain}")
            return c if c["status"] != "active" else None
        t0 = time.time(); chain = None
        while time.time() - t0 < 260 and not chain:
            chain = suspended()
            time.sleep(4)
        n_before = len(loop_msgs(events(rid)))
        check("l'auditeur suspend la chaîne avant l'épuisement du budget", bool(chain) and chain["suspendReason"] == "audit", f"statut {chain and chain['status']} raison {chain and chain['suspendReason']} après {n_before} messages, dépense {chain and chain['spent']}/{chain and chain['budget']}")
        time.sleep(15)
        warned = [e for e in events(rid) if e["type"] == "sent" and e["actor"] == "auditeur" and e["target"] in ("comite-1", "comite-2", "comite-3", "chef-projet", "ing-qualite")]
        check("l'auditeur prévient les humains", bool(warned), f"{len({e['target'] for e in warned})} destinataire(s)")
        log("  décision humaine : le chef de projet clôt la chaîne")
        closed = user("chef-projet", "POST", f"/chains/{gov_chain}/close", {"reason": "Boucle improductive entre Ingénierie et Essais : version de prompt défectueuse."})
        check("la chaîne est close par un humain", closed["status"] == "closed")
    finally:
        for a, p in originals.items():
            try:
                v = admin("POST", f"/admin/agents/{a}/versions", {"prompt": p})
                log(f"  version saine de {a} restaurée : {v['id']}")
            except Exception as e:  # noqa: BLE001
                log(f"  ! restauration de {a} impossible : {e}")
        admin("POST", f"/replay/runs/{rid}/end")
        exp = admin("POST", f"/replay/runs/{rid}/export", {"slug": SLUG})
        log(f"enregistrement exporté : data/scenarios/{exp['file']} ({exp['events']} événements)")
    # ---------- bilan ----------
    chains = {}
    for cid in (main_chain, gov_chain):
        try:
            chains[cid] = admin("GET", f"/chains/{cid}")
        except Exception:  # noqa: BLE001
            pass
    log("BILAN")
    for c in chains.values():
        log(f"  chaîne {c['id']} : {c['status']} · {c['spent']}/{c['budget']} messages · {c['tokensSpent']} tokens")
    ko = [c for c in report["checks"] if not c["ok"]]
    log(f"{len(report['checks']) - len(ko)}/{len(report['checks'])} vérifications réussies" + (" — échecs : " + "; ".join(c["label"] for c in ko) if ko else ""))
    return 1 if ko else 0


if __name__ == "__main__":
    sys.exit(main())
