# Orchestre d'agents sur Neo4j — PoC

Plateforme d'orchestration multi-agents où **Neo4j sert de bus (CDC) et de mémoire** : inbox, messages, routines, droits par chemins (ReBAC), fédération de graphes de connaissance, gouvernance (budget, auditeur, validations humaines) et traçabilité. Scénario : un incident terrain déclenche une modification produit. L'interface, le contenu de démo et les messages des agents sont en anglais (vidéo de démonstration) ; la documentation reste en français.

- Spécification : [`docs/spec.md`](docs/spec.md) — Règles du projet : [`CLAUDE.md`](CLAUDE.md) — Spikes et écarts : [`docs/spikes.md`](docs/spikes.md)
- Code : [`agent-orchestra-poc/`](agent-orchestra-poc/) (passerelle, consommateur CDC, runtimes d'agents, interface React)

## Démarrer

Prérequis : Docker, `make`, Node 22 (tests de navigateur). Créer `agent-orchestra-poc/.env` avec `GEMINI_API_KEY=…` et `LLM_PROVIDER=gemini` (jamais versionné), puis :

```bash
cd agent-orchestra-poc
make keygen      # génère ORCHESTRA_MASTER_KEY dans .env (sans l'afficher)
make seed        # Neo4j Enterprise (APOC, GDS), bases, utilisateurs, CDC, schéma, données synthétiques
make app         # passerelle, consommateur CDC, runtimes d'agents, interface → http://localhost:15173
```

Neo4j : HTTP 17474, Bolt 17687. Passerelle : 18000. Consommateur CDC : 18001. `make ui` lance l'interface sans les runtimes (donc sans appel LLM) ; `make reset` remet tout à zéro.

## Relecture et scénario

L'onglet **Relecture** rejoue le flux d'événements reconstruit depuis le graphe, ou un enregistrement fichier, sur la scène, le graphe et le journal : lecture/pause, vitesse ×1 à ×20, barre de temps, compression des temps morts, chapitres (incident, analyse, vote, lancement, gouvernance), suivi d'un agent. Un scénario réel est fourni : [`agent-orchestra-poc/data/scenarios/full-scenario.json`](agent-orchestra-poc/data/scenarios/full-scenario.json) (de l'incident à la gouvernance, avec la boucle légitime, le vote, le lancement, la relance et l'auditeur qui suspend une boucle sans fin).

```bash
make scenario   # remet la base à zéro, lance la pile et rejoue le scénario complet avec les vrais agents (≈ 5 min, ≈ 200 000 tokens Gemini)
```

## Tests

```bash
make test   # pytest : schéma, passerelle, tests de non-fuite des droits, CDC, runtimes (Neo4j de test)
make e2e    # Playwright sur une base propre, sans LLM ; unitaires de l'interface : cd ui && npm test
```

Licence Neo4j Enterprise : l'image est utilisée avec `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes` (à vérifier pour votre usage). Les mots de passe par défaut du compose sont des valeurs de développement local.
