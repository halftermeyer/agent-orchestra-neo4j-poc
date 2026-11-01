# agentic-orchestra — règles pour Claude Code

Plateforme d'orchestration multi-agents sur Neo4j (CDC = bus, graphe = mémoire).
La spécification fait foi : `docs/spec.md`. Lis-la entièrement avant toute modification de schéma ou de requête.

## Emplacement du code
- Le code va dans `agent-orchestra-poc/` (racine du dépôt). `docs/spec.md`, `CLAUDE.md` et `PROMPT_CC.md` restent au niveau au-dessus.
- `agent-orchestra-poc/.env` existe déjà (`GEMINI_API_KEY`, `LLM_PROVIDER`). Ajoute `.env` au `.gitignore` dès le premier commit, ne l'affiche jamais, ne le journalise jamais. La passerelle s'en sert comme valeur initiale tant qu'aucune clé n'a été enregistrée dans Paramètres → Modèles ; la clé enregistrée dans l'UI est prioritaire.

## Stack imposée
- Neo4j Enterprise (image Docker officielle, `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes`), plugins APOC et GDS. Pas d'Aura.
- Backend Python 3.12 : FastAPI, driver `neo4j` officiel, SDK `google-genai`. Un seul package `orchestra/` avec des services séparés : `gateway`, `cdc`, `runtime`.
- UI : React + Vite + TypeScript, `@neo4j-nvl/react` pour le graphe, Framer Motion pour la scène. Libellés de l'UI en français.
- `docker compose` pour tout lancer ; `make` pour les commandes courantes.
- Les bases (`orchestra`, `kgproduit`, `kgprojet`, composite `fed`), les utilisateurs (admin, gateway, cdc) et l'activation du CDC sont créés par un script d'init idempotent versionné (`db/init/`), jamais à la main.
- Ports exposés : 17474 (HTTP) et 17687 (Bolt), pour ne pas entrer en conflit avec une instance Neo4j locale déjà lancée.

## Règles non négociables
1. Cypher 25 partout (`CYPHER 25` en tête). Pas d'`elementId` comme clé métier.
2. Les agents ne touchent jamais la base : toute lecture/écriture passe par la passerelle, avec des requêtes figées et paramétrées, rangées dans `orchestra/gateway/queries/*.cypher`. Aucun Cypher construit par concaténation.
3. L'`agentId` vient du contexte d'authentification (jeton de service par runtime), jamais d'un argument fourni par le LLM.
4. Écriture en ajout seul : pas de liste chaînée, pas de pointeur `LAST`. Buckets par jour (`InboxDay`, `WorkDay`) avec `MERGE` sur clé de nœud.
5. On n'écrase pas : chaque transition d'état garde sa date (`submittedAt`, `workingAt`, `completedAt`, `startedAt`, `endedAt`…), indispensable pour la relecture.
6. Droits = chemins (ReBAC), avec la grammaire en liste blanche de la spec. Toute nouvelle source de partage est une branche explicite de la requête de périmètre.
7. Les secrets (clé Gemini) ne vont ni dans le graphe, ni dans le dépôt, ni dans les journaux, ni dans le navigateur. Stockage chiffré côté passerelle, clé maître dans `ORCHESTRA_MASTER_KEY`.
8. Toute écriture d'agent renseigne `txMetadata` (`agentId`, `chainId`).
9. Le consommateur CDC est idempotent et persiste un curseur par base.
10. Le budget par chaîne est vérifié de façon synchrone par la passerelle à chaque envoi.

## Façon de travailler
- Avance par phases (voir `PROMPT_CC.md`). À la fin de chaque phase : tests verts, résumé de ce qui a été fait, écarts éventuels avec la spec, puis **arrête-toi et attends ma validation**.
- Si une fonctionnalité Neo4j ne se comporte pas comme la spec le suppose, ne contourne pas en silence : note-le dans `docs/spikes.md` et propose une alternative.
- Tests : `pytest` pour le backend, avec une instance Neo4j de test (testcontainers ou le compose). Les tests de non-fuite des droits sont obligatoires.
- Commits petits et explicites, en anglais.
