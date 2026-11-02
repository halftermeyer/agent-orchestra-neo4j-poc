# Spikes — Phase 0

Version testée : **Neo4j 2026.09.0 Enterprise** (image `neo4j:2026.09.0-enterprise`), Cypher 5 et 25 disponibles, APOC (core) et GDS installés via `NEO4J_PLUGINS`. Driver Python `neo4j` 6.4.1. Scripts : `agent-orchestra-poc/spikes/`.

Résumé : toutes les hypothèses de la spec sont confirmées, avec quatre nuances (★) à intégrer aux phases suivantes.

## 1. `MATCH ACYCLIC` et `MATCH ANY` sur `-[:SUPERVISES]->*` ✅

Graphe : `a→b→c→a` (cycle) et `b→d`. Départ en `a`.

| Requête | Résultat |
| --- | --- |
| `MATCH ACYCLIC (me {id:'a'})-[:SUPERVISES]->*(x)` | `a, b, c, d` (chacun une fois ; `a` = chemin de longueur 0) |
| `MATCH ANY (me {id:'a'})-[:SUPERVISES]->*(x)` | `a, b, c, d` (un chemin par extrémité) |
| `MATCH (me {id:'a'})-[:SUPERVISES]->*(x)` (sans mot-clé) | `a, a, b, c, …` : doublons, le cycle est parcouru une fois |

★ Le motif `->*` inclut le chemin de longueur 0 : `me` fait partie de son propre périmètre, ce que la requête de périmètre de la spec suppose déjà (`a = me`). Le mot-clé `ACYCLIC` est donc à garder dans toutes les requêtes de supervision. `path` n'est pas lié implicitement (`MATCH ANY SHORTEST … length(path)` échoue) : il faut écrire `p = …`.

## 2. CDC ✅

- `ALTER DATABASE <db> SET OPTION txLogEnrichment 'FULL'` fonctionne (visible dans `SHOW DATABASES … options`). La base redémarre ; `db.cdc.current()` répond ensuite.
- `db.cdc.query(cursor, selectors)` : les événements portent `txId`, `seq`, `metadata`, `event.eventType` (`n`/`r`), `event.operation` (`c`/`u`/`d`) et `event.state.after.properties`. Le sélecteur `[{select:'n', labels:['Message']}]` filtre bien.
- ★ **Privilèges minimaux d'un utilisateur CDC** : `ACCESS` sur la base **et** `EXECUTE BOOSTED PROCEDURE db.cdc.*` ON DBMS. Un `EXECUTE PROCEDURE` simple est refusé ; `MATCH {*}` n'est pas nécessaire. Sans `ACCESS` sur la base, c'est refusé.
- ★ Conséquence sécurité : l'utilisateur `cdc` lit **toutes** les propriétés de tous les événements sans droit `MATCH`. Le compte CDC doit rester interne (jamais exposé à l'UI) ; le filtrage par droits se fait dans le routeur.
- Rétention des logs de transaction fixée à `2 days` dans le compose (`db.tx_log.rotation.retention_policy`) pour que le curseur survive à un arrêt du consommateur.

## 3. Base composite `fed` ✅

`CREATE COMPOSITE DATABASE fed` + alias `fed.orchestra`, `fed.kgproduit`, `fed.kgprojet`. Fonctionnent :

- `USE fed.kgproduit MATCH …` ;
- `UNWIND ['kgproduit','kgprojet'] AS g CALL (g) { USE graph.byName('fed.' + g) MATCH … RETURN … } RETURN …` : nom calculé dans un `CALL` de portée explicite, avec résultats des deux KG.

À retenir : `graph.byName` attend le nom **qualifié** (`fed.kgproduit`). Les noms de graphes doivent venir d'une liste blanche côté passerelle (jamais d'une entrée LLM).

## 4. Index vectoriel avec filtre ✅ (clause `SEARCH` disponible)

- `db.index.vector.queryNodes` est **déprécié** (remplacé par `SEARCH`) ; un post-filtre sur le top-10 ne rend que 5 résultats sur 10 demandés (50 % de perte).
- ★ `SEARCH f IN (VECTOR INDEX … FOR $v WHERE f.memoryId = 'm1' LIMIT 10)` ne fonctionne que si la propriété de filtre est déclarée à la création : `CREATE VECTOR INDEX … FOR (f:Fact) ON (f.embedding) WITH [f.memoryId] OPTIONS {…}`. Sinon : `22ND3 … not an additional property`. Avec la déclaration : 10 résultats, tous du bon `memoryId`, et `IN [...]` fonctionne aussi.
- Décision proposée pour la phase 1 : index `fact_embedding` avec `WITH [f.memoryId]`. Le filtre du périmètre ReBAC se fait par `memoryId IN $scopeIds` ; le filtre `asOf` (`validFrom`/`validTo`) reste un post-filtre. Je demande donc `LIMIT` large (k×3) avant le post-filtre `asOf`. Les dimensions de l'embedding dépendent du modèle Gemini : à fixer en phase 2.

## 5. `apoc.util.validate` dans une écriture ✅

`CREATE (x) WITH x CALL apoc.util.validate(true, 'budget exceeded %d', [5])` lève une erreur (`ProcedureCallFailed`) et la transaction est annulée : le nœud n'est pas persisté. Avec `false`, la requête passe. Utilisable pour le budget de chaîne et les gardes d'écriture, la passerelle devant mapper l'erreur en HTTP 4xx.

## 6. Latence écriture → événement CDC ✅

Écrivain et poller découplés (écriture à intervalle aléatoire de 50–400 ms, 30 messages par essai, Docker local, une instance) :

| Polling | p50 | moyenne | p95 | max |
| --- | --- | --- | --- | --- |
| 100 ms | 71 ms | 64 ms | 116 ms | 120 ms |
| 250 ms | 123 ms | 111 ms | 236 ms | 254 ms |
| 500 ms | 256 ms | 249 ms | 466 ms | 516 ms |

La latence suit ≈ intervalle/2 : le CDC lui-même ajoute quasi rien (< 15 ms mesuré en lecture immédiate après commit). **Choix proposé : 100 ms** (charge négligeable en local). Une première mesure avec un écrivain synchrone était invalide (le premier poll trouvait toujours l'événement) et a été écartée.

## Écarts avec la spec

Aucun bloquant. Points d'attention : (★) ci-dessus ; `SEARCH` rend le post-filtre inutile pour les droits mais pas pour `asOf`.

## Notes de phase 1

- **Écart / ajout à valider** : la spec exige de vérifier « le droit sur le `KnowledgeGraph` » sans nommer la relation. Le seed introduit `(:Agent)-[:CAN_QUERY {mode:'read'}]->(:KnowledgeGraph)`. Ce sera une branche explicite de la requête de périmètre (règle 6).
- Sans privilège `MATCH`, un utilisateur lit **zéro ligne** (pas d'erreur) : le compte `cdc` ne voit aucun nœud en direct, mais `db.cdc.query` lui renvoie tout.
- Le rôle `PUBLIC` a `EXECUTE PROCEDURE *` par défaut ; le `GRANT EXECUTE PROCEDURE apoc.util.*/gds.*` de `gateway_rw` est donc redondant mais explicite.
- La passerelle a besoin de `NAME MANAGEMENT` sur `orchestra` (création dynamique de labels/types de relation à l'exécution).
- `VOTED` porte `approvalId` et `personId` pour supporter la contrainte d'unicité de relation (le couple ne peut pas être exprimé autrement).

## Notes de phase 2 (passerelle)

- **Clé de session** : `Session.triggerMsgId = <messageId>@<agentId>` (et `direct:<messageId>@<personId>` pour un message d'humain). Un même message envoyé à deux inbox réveillerait deux agents avec le même `messageId` ; l'unicité globale de la spec exigeait donc une clé composite. Le lien `TRIGGERED_BY` pointe toujours vers le `Message`.
- **Requête de périmètre** : la requête de référence est reprise telle quelle, avec une restriction pour les `:Person` supervisées (branches mémoire propre et inbox exigent `a = me OR NOT a:Person`). La branche `HAS_WORKSPACE·HAS_DAY·OPENED` de la grammaire n'est pas implémentée : aucune relation `CAN_READ` ne part d'une `Session` dans le PoC (règle 6 : pas de branche sans besoin).
- **Chaîne** : en plus de `budget`/`spent` (messages), `tokenBudget`/`tokensSpent`. Un budget épuisé passe la chaîne en `suspended` (avec `suspendedAt`, `suspendReason`) dans la transaction qui constate le dépassement ; la reprise est humaine (`resumedAt`). Les boucles déclarées (`stopCriterion`, `maxTurns`) ne sont créées que par l'administrateur pour l'instant.
- **Journal des accès** : nœuds `(:AccessLog {agentId, kind, granted, targets, at})` reliés à l'agent par la propriété `agentId`, pas par une relation (évite un super-nœud) ; à rebucketer par jour si le volume le justifie.
- **`CAN_SHARE`** : relation `(:Agent)-[:CAN_SHARE]->(:Memory)` ajoutée pour le re-partage (« pas de cascade sans CAN_SHARE »).
- **Syntaxe Cypher 25 rencontrée** : `ORDER BY` après `RETURN` n'accepte que les alias ; la variable de chemin se place avant le sélecteur (`MATCH path = ANY (a)<-[:R]-+(b)`).
- **Gemini réel** (clé de l'environnement) : liste de 46 modèles dont `gemini-2.5-flash` ; embeddings `gemini-embedding-001` en 768 dimensions ; appel d'outil et comptage de tokens validés.
- **Port** de la passerelle : 18000 (`make gateway`). Jetons : `python -m orchestra.gateway.tokens svc|user|admin <id>` (HMAC de la clé maître, sans stockage). `make keygen` ajoute `ORCHESTRA_MASTER_KEY` à `.env` sans l'afficher.
- **Reste pour les phases suivantes** : engagements (`commit`), `ABOUT_EVENT` du routeur, `AUDITS` en lecture épisodique pour l'auditeur, connexion de démonstration des utilisateurs de l'UI.

## Notes de phase 3 (consommateur CDC)

- **`keys` du CDC = clés de nœud uniquement.** Une contrainte d'unicité simple ne renseigne pas `keys` (constaté sur `Message`). Pour identifier les entités à partir des seuls événements (le compte `cdc` ne peut rien lire d'autre), ces contraintes sont passées en `NODE KEY` : `Agent.id`, `Message.id`, `Session.triggerMsgId`, `Inbox.id`, `Memory.id`, `Chain.id`, `Tool.name`, `ToolCall.idempotencyKey`, `Approval.id`, `Entity.id` (KG). Plus strict que l'unicité de la spec, donc compatible. Les anciennes contraintes sont supprimées par le script d'init (`DROP … IF EXISTS`) ; noms : `*_key`.
- **Curseur dans un fichier, pas dans le graphe.** Écrire le curseur dans la base surveillée produit un événement CDC, donc un nouveau curseur : boucle infinie. Un fichier JSON par installation (volume `cdc-data`), écriture atomique, un curseur par base. Premier démarrage : position courante (`db.cdc.current`), le seed n'est pas rejoué. Non géré : un curseur plus ancien que la rétention des logs (2 jours dans le compose).
- **Écritures du consommateur = passerelle.** Le consommateur lit le CDC avec l'utilisateur `cdc` et n'écrit que via `/internal/*` (jeton `sys`, dérivé de la clé maître) : dépôt des messages (`/internal/deliver`), avancement des routines, synchronisation des `EntityRef`. Les `txMetadata` portent l'agent d'agissement et la chaîne.
- **Messages système** (routines, topics, pont) : `Message.from` = `routine:<id>` ou `pont-kg`, `actingAgent` = l'agent dont `CAN_SEND_TO` et le budget s'appliquent, pas de `Session`/`SENT` (aucun agent n'écrit). Ids déterministes (`evt:<routine>:<msg>`, `raw:<db>:<tx>`, `<routine>@<créneau>`) : la clé de nœud sur `Message.id` fait l'idempotence. Une livraison dans sa propre inbox est autorisée sans `CAN_SEND_TO` (les routines du seed n'en déclarent pas).
- **Chaînes** : une routine d'événement hérite la chaîne du message déclencheur ; un créneau cron ouvre sa propre chaîne ; une transaction de KG ouvre la sienne, sauf si son `txMetadata` porte un `chainId` (la chaîne causale de la modification est alors reprise).
- **Pont KG** : réalisé par le consommateur agissant comme `pont-kg` (agent à règles) ; pas de runtime dédié nécessaire. Un message par transaction, `kgDb`, `txId`, 200 changements au plus (`truncated`), identifiants d'entité tirés des clés de nœud.
- **Routines** : `nextRunAt` calculé côté application (croniter, fuseau de la routine) ; `misfire = skip` ignore un créneau en retard de plus de 60 s ; une minuterie `once` a `misfire = fire` par défaut (une relance ne doit pas disparaître après un arrêt). `CAN_SEND_TO` est vérifié à la création (`POST /routines`) et à chaque déclenchement (échec enregistré dans `lastError`).
- **Réveil** : `/ws/wake` (jeton de service, un runtime ne reçoit que ses réveils) ; rattrapage par `GET /inbox/pending`. Pas de réveil pour un agent en quarantaine ni pour une chaîne suspendue. **Flux** : `/ws/events` (historique récent rejoué à la connexion), `GET /stats` (retard CDC → traitement).
- **Mesures** (Docker local, polling 100 ms) : envoi → réveil du runtime p50 82 ms, p95 86 ms (15 essais) ; retard commit → traitement p50 ≈ 110 ms en réel.
- **Limites connues** : une seule boucle séquentielle pour les trois bases ; pas de partitionnement par `entityId` (prévu pour les interpréteurs, phase 4) ; les événements `RECEIVED` mis à jour (statuts) ne sont pas encore exploités.

## Notes de phase 4 (runtimes d'agents)

- **Un processus, un fil par agent** (`python -m orchestra.runtime`) : réveil par `/ws/wake`, rattrapage par `/inbox/pending`, un seul traitement à la fois par agent (l'ordre par `entityId` des interpréteurs est donc garanti ; pas de partitionnement tant qu'il n'y a qu'un interpréteur). Les runtimes n'ont ni clé LLM ni accès à la base ; ils appellent la passerelle avec le jeton de leur agent. Simplification PoC : le processus dérive les jetons de la clé maître (chaque `AgentRunner` n'utilise que le sien) ; en production chaque runtime recevrait seulement son jeton.
- **Boucle** : session (idempotente) → contexte (prompt de l'`AgentVersion`, mandat, destinataires autorisés, catalogue des modèles KG, engagements ouverts, fil de la chaîne limité à ce que l'agent a envoyé/reçu) → génération ↔ outils, au plus 10 tours → fermeture (`completed`, `failed`, `input-required`). Chaque outil est tracé par un `ToolCall` (`PRODUCED` vers le fait ou le message) ; un refus est renvoyé au LLM comme résultat d'outil et l'appel est marqué `failed`. Budget épuisé / chaîne suspendue / limite de tours : session `failed`, sans réessai.
- **Portes à règles avant le LLM** : engagement déjà soldé → pas d'appel. Auditeur : `POST /audit/scan` d'abord ; le LLM n'est appelé que sur les chaînes candidates dont l'état a changé depuis le dernier jugement.
- **Auditeur** : signaux calculés dans le graphe — cycles (projection GDS sur une fenêtre glissante des échanges entre agents audités, `gds.scc.stream`), messages répétés (similarité moyenne d'embeddings ≥ 0,92), budget ≥ 80 %, rythme ≥ 15 messages/min. Accès : épisodique des agents qu'il `AUDITS` (messages envoyés), jamais les mémoires. `ratePerMinute` a été relevé de 8 à 15 après un essai réel : une analyse légitime de 13 messages en 90 s déclenchait un jugement LLM inutile.
- **Engagements** : `commit` crée `Commitment` + une routine `once` (`rt-commit-<id>`, `misfire = fire`) qui relance le débiteur à l'échéance, émise par le créancier s'il peut lui écrire. Solder (`fulfills`) désactive la relance ; sinon la porte à règles évite un appel LLM pour un engagement déjà soldé.
- **`launch_modification`** : effet d'un outil irréversible, exécuté par la passerelle avec un utilisateur dédié `kgcurator` (écriture dans les KG uniquement, jamais exposé aux agents), seulement si la validation est `approved`, avec les arguments *figés au moment de la demande*. Nouvelle `ProductVersion` (`SUPERSEDES`), pièce retirée (`retiredIn`), liens `CONTAINS` remplacés (`removedIn`/`addedIn`) ; les modèles de requête ignorent les liens retirés. Idempotent par validation. La transaction porte le `chainId` : le pont reprend la chaîne de la modification.
- **Réveil sur décision** : le consommateur dépose un message système `approval-decided` chez le demandeur et un message `chain-suspended` chez l'auditeur (budget/tokens épuisés).
- **CPA** : `orchestra/runtime/cpa.py` (passe avant/arrière, marges, chemin critique, simulation de retard), testé contre la passe avant du seed.
- **Seed** : un prompt modifié crée une nouvelle `AgentVersion` (jamais de réécriture) ; les KG sont chargés en `ON CREATE` seulement (une première version réécrivait des propriétés identiques et remettait `VER-1.0` à `current`, ce qui générait des événements CDC en relançant `make seed` sur un système vivant).
- **Essai réel (Gemini 2.5 Flash)** : incident INC-001 → Qualité (qualifie, 3 faits, demande au Coordinateur avec mémoire jointe) → Coordinateur (3 demandes, engagement) → Essais/Ingénierie/Planification (proposition acceptée du premier coup, retard de 11 jours par CPA) → synthèse au chef de projet → validation demandée (`input-required`) → 2 votes → `launch_modification` → `VER-1.1` dans le KG → pont → interpréteur → Essais et Planification réveillés. ≈ 55 s jusqu'à la demande de validation, ≈ 105 k tokens sur la chaîne (budget par défaut 200 k).
- **Constats** : (1) le payload brut d'un lot KG, avec ses identifiants d'événements CDC, noyait l'interpréteur (deux `set_status`, aucune publication) : les `eventId` sont retirés du texte vu par le LLM et le prompt impose la publication ; (2) la boucle légitime Ingénierie ↔ Essais n'a pas eu lieu parce que le premier candidat était couvert par des essais : la phase 6 choisira l'incident (ou l'état des essais) pour la provoquer ; (3) un événement CDC n'est lisible qu'un instant après le commit : les tests laissent un temps de stabilisation.

## Notes de phase 5 (interface)

- **Pile** : React 19 + Vite + TypeScript, `@neo4j-nvl/react` 2.0 (rendu `canvas`, robuste sans WebGL), Framer Motion. NVL 2.0 exige React 19. Libellés en français. L'interface ne parle qu'à son serveur (nginx en production, proxy Vite en développement) : `/api` → passerelle, `/stream` → consommateur CDC (WebSocket). Aucune clé LLM dans le navigateur ; seul un jeton de démonstration est gardé dans `sessionStorage`.
- **Connexion de démonstration** (`ORCHESTRA_DEMO_LOGIN=1`, activée par le compose, désactivée par défaut) : on choisit une personne ou l'administrateur, sans mot de passe. À ne jamais activer hors démonstration ; une vraie installation brancherait OIDC (`Agent:Person.oidcSub` est prévu). Aucun agent logiciel n'est connectable.
- **Chat** : l'inbox de la personne connectée (et ce qu'elle a envoyé), par conversation (chaîne). Déclaration d'un incident préparé (ingénieur qualité), validations en attente avec vote (comité, délégués `ACTS_FOR` inclus).
- **Scène** : 13 postes, huit états d'avatar alimentés par le flux normalisé (`avatarState.ts`, fonction pure testée) : réveillé (sursaut, boîte qui clignote), réfléchit (bulle `set_status`), outil (icône + progression), envoie (enveloppe vers le destinataire), apprend (étincelle vers l'étagère), attend (sablier, grisé, persiste après la fin de session), erreur (rouge, secousse), repos (respiration). Au chargement, l'état initial vient de `/graph/state` ; l'historique rejoué par le serveur garde sa vraie date (événement de plus de 5 s = animation déjà expirée). Un agent « occupé » sans événement depuis 20 s (réveillé seulement) ou 60 s retombe au repos (runtime arrêté).
- **Graphe (NVL)** : topologie (supervision, abonnements, envois autorisés, audit, accès KG), flux (arêtes allumées 8 s), fiche agent (version, mandat, outils, routines, engagements, derniers statuts et appels), droits (la vue reconstruit les chemins `SUPERVISES*` + relation terminale ; un test garantit qu'elle montre exactement le périmètre calculé par `/scope`), KG (voisinage d'une pièce ou d'une tâche, avec contrôle `CAN_QUERY` ; pièces retirées en gris).
- **Frise** : routines déclenchées et à venir, appels d'outils (barres début→fin), votes, engagements, une ligne par acteur.
- **Paramètres → Modèles** : administrateur seulement ; clé en écriture seule (4 derniers caractères et date réaffichés), tester (candidate ou enregistrée), remplacer, supprimer, choix du modèle. Un test de navigateur vérifie que la clé réelle de l'environnement n'apparaît ni dans le DOM, ni dans les stockages du navigateur, ni dans les réponses de la passerelle.
- **Endpoints ajoutés** : `/demo/*`, `/chat/messages`, `/approvals`, `/graph/{topology,state,agent,rights,kg}`, `/timeline`. Les personnes ont maintenant `CAN_QUERY` (ing-qualite, comité : KG Produit ; chef de projet : les deux) pour que la vue KG respecte les droits comme pour les agents. Les vues de supervision (topologie, droits) montrent des *métadonnées* (qui peut lire quoi), jamais le contenu des mémoires.
- **Corrections trouvées par les tests de navigateur** : (1) la session « directe » d'un message d'humain n'était jamais fermée, donc la personne apparaissait occupée pour toujours : elle est close dans la transaction d'envoi ; (2) une réponse tardive de la vue Droits écrasait la sélection courante (requêtes périmées désormais ignorées) ; (3) un curseur CDC antérieur à une base recréée bloquait le consommateur en boucle d'erreurs (`FutureIdentifier` / `InvalidIdentifier`) : il repart de la position courante, avec avertissement et compteur `cursorResets`.
- **Tests** : 22 unitaires (Vitest : états des avatars, horloge des événements, transformations de graphe), 6 de navigateur (Playwright/Chromium, sur le build de production servi par nginx, sans appel LLM) via `make e2e` qui repart d'une base remise à zéro. Lancer l'interface : `make ui` (http://localhost:15173) ou `make app` avec les runtimes.

## Notes de phase 6 (relecture et scénario)

- **Reconstruction du flux** : `GET /replay/events` rejoue le graphe en un `UNION ALL` par type d'événement (`replay_events.cypher`), trié par `t`, au même format normalisé `{t, type, actor, target, payload}` que le direct. Un test garantit que, sur un même enchaînement (session, statut, appels d'outils réussis et en échec, fait appris, message, engagement, validation en attente puis votes), le multiensemble `(type, acteur, cible)` reconstruit est **identique** au flux produit en direct par le consommateur CDC. Approximations assumées : le réveil est rejoué pour chaque propriétaire d'inbox (la suspension ou la quarantaine postérieures ne sont pas rejouées) ; l'acteur d'une suspension de chaîne est l'auditeur (relation `SUSPENDED`) ou `gateway`.
- **Deux défauts du flux direct trouvés par cette comparaison** : la fin d'un appel d'outil perdait le nom de l'outil (la relation `OF` n'existe que dans la transaction de création) ; le nom est maintenant dénormalisé sur le `ToolCall` (`tool`), donc le flux ne dépend plus de l'état d'une transaction à l'autre. Le `kind` du message est aussi porté par l'événement `sent` en direct (il alimente les chapitres).
- **Enregistrer** : un `Run` (`startedAt`, `endedAt`) marque la fenêtre à relire (le graphe *est* l'enregistrement : rien n'est dupliqué) ; `POST /replay/runs/{id}/export` fige les événements dans `data/scenarios/<nom>.json`, fichier portable et versionnable qui survit à la remise à zéro de la base. Lecture ouverte aux personnes ; création et export réservés à l'administrateur ; nom de fichier en liste blanche (pas d'évasion de répertoire).
- **Lecteur** (`replayEngine.ts`, pur et testé) : temps virtuel × vitesse (×1, ×2, ×5, ×10, ×20) ; compression des temps morts (un écart de plus de 4 s saute jusqu'à 0,8 s avant l'événement suivant) ; la barre de temps recalcule l'état en rejouant tout avec les vraies dates des événements, puis fait expirer les animations dépassées, puis passe les échéances dans l'horloge murale (`rebase`) ; chapitres repérés dans le flux (incident, analyse, vote, lancement, gouvernance) ; suivi d'un agent (anneau sur son poste, les autres s'estompent, journal filtré). La scène, le graphe et le journal reçoivent le **même contexte** que le direct (états, enveloppes, flux récent) : ils ne voient pas la différence. Les compteurs de boîtes et de mémoire sont recalculés à l'instant rejoué.
- **Défauts de ta session de démonstration, corrigés** : (1) le Coordinateur, réveillé à chaque rapport de spécialiste, demandait la validation du comité **à chaque fois** (3 validations en attente pour une même décision) ; le dédoublonnage est dans la passerelle (une demande en attente par agent, outil et chaîne ; la suivante renvoie l'existante) et le prompt interdit de répéter la demande ; (2) une personne ne pouvait pas clore une chaîne improductive : `POST /chains/{id}/close` (décision humaine, définitive : plus aucun envoi, pas de reprise).
- **Incident du scénario** : INC-001 est choisi par le générateur (`loop_parts`) pour provoquer la boucle légitime : la pièce est couverte et partagée, son premier candidat de remplacement n'est couvert par aucun essai (Essais le refuse), le deuxième l'est (Essais l'accepte). Les échéances d'engagement des prompts sont courtes (2 et 3 minutes) pour que la relance arrive pendant la démonstration.
- **Scénario réel** (`make scenario`, Gemini 2.5 Flash, ≈ 5 minutes, ≈ 200 000 tokens) : 17 vérifications sur 17 : incident routé par abonnement ; demande d'impact ; trois analyses ; **boucle légitime** (2 propositions, 1 refus, accord) ; rapports d'essais, de planning et d'ingénierie ; engagements ; **une seule** validation en attente ; quorum 2-sur-3 ; lancement (`VER-1.1`, pièce retirée de la nomenclature) ; pont, interpréteur BOM, réveil d'Essais et de Planification ; **relance d'un engagement** par minuterie ; gouvernance. Chaîne principale : 28/90 messages, 148 k tokens. Enregistrement : `data/scenarios/scenario-complet.json` (381 événements, 5 min 08 s).
- **Chapitre gouvernance** : pour obtenir un aller-retour réellement sans fin entre deux agents LLM, le script injecte une **version défectueuse** d'Ingénierie et d'Essais par l'API d'administration (`AgentVersion` + `SUPERSEDES`, comme un vrai déploiement de prompt) : l'un propose sans conclure, l'autre refuse sans conclure. Le Coordinateur n'a pas relayé la demande du chef de projet ; le script amorce alors la boucle par un message système (routine), et le dit. L'auditeur détecte le cycle (GDS) et les répétitions (embeddings) après 17 messages (19/50 du budget), suspend la chaîne (`audit`), prévient les 5 humains ; le chef de projet la clôt ; les versions saines sont restaurées (nouvelles versions, jamais d'écrasement).
- **Défaut réel trouvé par le premier essai du scénario** : Ingénierie appelait `query_kg` avec `template: "part_info(partId)"` ou `"produit/part_info(partId)"` (signature recopiée du catalogue), obtenait 404 sur chaque appel et épuisait ses 10 tours sans jamais proposer de pièce. Trois corrections : catalogue du prompt non ambigu (`kg="produit", template="part_info", params={"partId": <str>}` et consigne « le nom seul »), normalisation tolérante côté runtime (préfixe, parenthèses, graphe déduit du catalogue), et une erreur 404 qui liste les modèles valides.
- **Limites connues** : le scénario dépend du comportement des LLM (le script attend chaque événement avec un délai et signale ce qui manque plutôt que d'échouer silencieusement) ; Ingénierie peut proposer deux fois la même pièce quand elle est réveillée deux fois (non corrigé, inoffensif) ; le chapitre « gouvernance » est détecté par une suspension de chaîne (`error` avec `chainId`) ou un message `chain-suspended`.

## Notes de phase 6 bis (passage de l'interface et de la démo en anglais)

- **Décision** (2026-11-02) : interface, contenu de démo (noms et titres des agents et des humains, mandats, prompts, descriptions d'incident, données synthétiques) et messages des agents en anglais, pour une vidéo de démonstration en anglais. Règle de `CLAUDE.md` mise à jour. Restent en français : la spec, ces notes et les commentaires de code. Identifiants techniques inchangés (ids d'agents, noms de bases, topics `kg.produit.raw` et `produit.bom-changes`, ids de KG) : ils viennent de la spec.
- **Ce qui a changé** : libellés de l'UI (`labels.ts`, tables renommées `*_LABEL`), messages d'erreur de la passerelle (visibles dans l'UI et lus par les LLM), descriptions d'outils, consignes communes et contexte de session des runtimes, notifications du consommateur, prompts et mandats du seed, noms de pièces, d'essais, de tâches et d'incidents. Les listes du générateur gardent la même longueur et le même ordre : la structure des données est identique (INC-001 reste la pièce PRT-0102 qui provoque la boucle légitime), seuls les libellés changent.
- **Défaut trouvé en rejouant le nouvel enregistrement à ×20** : une note brève (ex. « I approve ») était effacée par un événement qui suivait de 0,5 s (temps réel) ; elle a désormais sa propre durée de vie (`note`/`noteUntil`), testée.
- **Nouvel enregistrement** `data/scenarios/full-scenario.json` (451 événements, 5 min 42 s ; remplace `scenario-complet.json`) : 17 vérifications sur 17, boucle légitime (2 propositions, 1 refus), une seule validation, lancement, relance, et gouvernance. Variabilité observée entre deux exécutions : l'auditeur suspend la boucle défectueuse après 17 messages (première exécution) ou 38 messages (budget 42/50 : marge réduite mais respectée) selon la cadence du LLM et le moment de la minute où passe sa routine.
