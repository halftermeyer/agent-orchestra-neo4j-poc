# Prompt de lancement pour Claude Code

Lis `CLAUDE.md` puis `docs/spec.md` en entier. Le code va dans `agent-orchestra-poc/`. Tu construis le PoC décrit dans la spec, phase par phase. Après chaque phase, arrête-toi et attends ma validation.

## Phase 0 — Spikes (vérifier les hypothèses de la spec)
Monte un `docker-compose.yml` minimal avec Neo4j Enterprise (APOC, GDS), puis vérifie et documente dans `docs/spikes.md`, avec la version exacte de Neo4j :
- `MATCH ACYCLIC` et `MATCH ANY` sur `-[:SUPERVISES]->*` (résultats sur un petit graphe avec un cycle) ;
- activation du CDC (`ALTER DATABASE … SET OPTION txLogEnrichment 'FULL'`), `db.cdc.current`/`db.cdc.query`, privilèges minimaux d'un utilisateur dédié au CDC ;
- base composite `fed` avec alias vers `orchestra`, `kgproduit`, `kgprojet`, et `USE graph.byName(...)` avec un nom calculé dans un `CALL` ;
- index vectoriel avec filtre (`SEARCH` si disponible, sinon post-filtre) ;
- `apoc.util.validate` dans une écriture.
Mesure aussi la latence écriture → événement CDC avec un polling à 100, 250 et 500 ms.

## Phase 1 — Schéma et données
- Contraintes et index de la spec (`db/schema.cypher`), appliqués au démarrage.
- Seed de la base d'orchestration : agents du scénario (Coordinateur, Qualité, Ingénierie, Essais, Planification, Pont KG, Interpréteur BOM, Auditeur) et humains (ingénieur qualité, comité de 3 personnes avec inbox partagée, chef de projet), mandats, versions, inbox, topics (`incidents`, `kg.produit.raw`, `produit.bom-changes`), `SUPERVISES`, `CAN_SEND_TO`, `CAN_USE`, routines.
- Générateur de données synthétiques déterministe (graine fixe) : KG Produit (~200 pièces sur 3-4 niveaux de BOM, ~50 essais avec couverture, versions), KG Projet (~30 tâches avec dépendances, ressources), ~10 incidents prévus. Produit fictif, aucun nom réel.

## Phase 2 — Passerelle
- API FastAPI : envoi de message (avec mémoire jointe, multi-destinataires, contrôle `CAN_SEND_TO`, budget de chaîne), ouverture de session idempotente, `set_status`, enregistrement/révision de `Fact`, retrieval mémoire (périmètre ReBAC + recherche vectorielle + filtre `asOf`), appels d'outils tracés (`ToolCall`, `idempotencyKey`), approbations et votes, lecture KG (requêtes modèles), requête fédérée.
- Abstraction du fournisseur LLM (interface : génération, appel d'outils, embeddings, comptage des tokens) avec une implémentation Gemini.
- Paramètres → Modèles : endpoints pour enregistrer (écriture seule), tester (liste des modèles), remplacer, supprimer la clé ; stockage chiffré.
- Journal des accès dans le graphe.
- Tests de non-fuite (mémoire d'un pair, `private`, `snapshot` postérieur, partage expiré, supervision d'un `:Person`).

## Phase 3 — Consommateur CDC
- Polling avec un curseur persistant par base ; réveil des runtimes ; routage des topics (filtres structurés) ; planificateur des routines (`cron`, `once`, `event`, `misfire = skip`) ; pont KG (un message par transaction) ; synchronisation des `EntityRef`.
- Flux d'événements normalisé `{t, type, actor, target, payload}` diffusé en WebSocket.

## Phase 4 — Runtimes d'agents
- Boucle générique d'agent LLM avec les outils : `send_message`, `set_status`, `remember`, `recall`, `query_kg`, `commit`, `request_approval`, et pour la Planification un outil CPA (passe avant/arrière, chemin critique, simulation de retard).
- Agents à règles (pont KG) et auditeur (signaux GDS + jugement LLM sur les candidats, pouvoir limité à la suspension).
- Prompts et mandats du scénario.

## Phase 5 — Interface
Chat (inbox de l'humain connecté, sélection de l'utilisateur pour la démo), scène avec avatars animés selon les états de la spec, graphe NVL (topologie, flux, fiche agent, droits avec chemin surligné, KG), frise, Paramètres → Modèles.

## Phase 6 — Relecture et scénario
Endpoint de reconstruction du flux depuis le graphe, contrôles de lecture (vitesse ×1–×20, barre de temps, compression des temps morts, chapitres, suivi d'un agent). Exécute le scénario complet de bout en bout, y compris la boucle légitime et le chapitre gouvernance, et enregistre-le pour la relecture.

Commence par la phase 0.
