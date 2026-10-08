# Spécification de rapport adaptée au projet — PIQBIT

Statut : **gabarit `pfe_report_spec_project_template.md` complété**, uniquement
avec des faits confirmés par inspection du dépôt. Tout ce qui n'a pas pu être
confirmé reste en `TODO:` visible.

- Révision de preuve : dépôt `PIQBIT`, `HEAD = c8e1bb7` (2026-09-15 15:47 +0200),
  **arbre de travail modifié** — 78 fichiers modifiés, 5 supprimés, 17 non
  suivis au 2026-09-22. 520 fichiers suivis.
- Date d'inspection : **2026-09-22**.
- Conséquence de reproductibilité : la majorité des constats ci-dessous décrit
  l'**arbre de travail**, pas le commit `c8e1bb7`. Avant soumission, le travail
  doit être committé et cette spécification réancrée sur une révision stable.
  `TODO: figer une révision de rédaction et la citer partout.`

---

## Objet et périmètre

- Titre de travail : PIQBIT — plateforme de recrutement augmentée par l'IA.
- Titre officiel : `TODO: M-01`.
- Établissement et filière : `TODO: M-02`.
- Organisme d'accueil : `TODO: M-05`.
- Langue du rapport : `TODO: M-04`.
- Langues des résumés : `TODO: M-04`.
- Période académique : `TODO: M-02`.
- Contraintes de confidentialité : `TODO: M-14`.

Formulation confirmée par les sources : PIQBIT est un **système de suivi des
candidatures (ATS) web**, doublé de services d'aide à la décision — analyse
automatique de CV, notation pondérée des candidats, rapprochement sémantique
candidat/offre, prédiction de fourchette salariale par apprentissage
automatique et assistance à la négociation, puis contractualisation et
intégration RH.

- Périmètre **implémenté et vérifié** : voir « Périmètre fonctionnel ».
- Hors périmètre **constaté** : aucune télémétrie applicative (métriques,
  traces, tableaux de bord, alertes) ; aucune infrastructure d'hébergement
  cible ; aucun test de charge, de résilience ou de restauration.

---

## Sources de preuve réellement consultées

| Source | Révision ou date | Usage prévu dans le rapport | Fiabilité |
| --- | --- | --- | --- |
| Dépôt `PIQBIT` (arbre de travail) | `c8e1bb7` + modifications locales, inspecté le 2026-09-22 | Chapitres 3, 4, 5 | **Autorité** sur l'implémentation |
| `Cahier_des_Charges_PIQBIT.docx` | v1.0, 06 mai 2026 | Chapitres 1 et 2 (acteurs, exigences FR/NFR, contraintes, planning prévisionnel) | **Approuvée mais ancienne** — périmètre très inférieur à l'implémenté (voir « Conflits ») |
| `DOCUMENTATION.md` | « Dernière mise à jour : 2026-06-14 » | Chapitres 3 et 4 (intentions de conception, historique des incréments V1 → V1.8.1) | **Partiellement périmée** (voir « Conflits ») |
| `backend/datasets/README_tunisia_it_salaries.md` | non daté ; artefacts associés datés 2026-09-10 | Chapitre 4 (volet ML salaire), chapitre 5 (métriques de modèle) | Autorité, **corroborée par l'artefact** `salary_model_piqbit.p` |
| `.github/workflows/ci.yml` | arbre de travail | Chapitre 5 (portes de qualité) | Autorité sur la **configuration**, pas sur l'exécution |
| `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` | arbre de travail | Chapitre 3 (vue de déploiement), chapitre 5 | Autorité sur la configuration |
| `backend/app/core/rbac_policy.csv`, `rbac_model.conf` | arbre de travail | Chapitres 3 et 4 (autorisation) | Autorité |
| `gantt_diagram.png` + `generate_gantt.py` | début planifié 2026-05-09, horizon 180 j | Chapitre 1 (planification) | **Prévisionnel uniquement** — ne prouve aucun déroulement |
| Campagne `validation_runs/2026-09-22_validation_summary.md` | 2026-09-22 | Chapitre 5 | Preuve datée, portée limitée décrite dans la campagne |
| `TODO: entretien ou validation par l'encadrant` | — | Chapitre 1 | `TODO: M-09, M-10, M-11` |

### Conflits constatés entre sources — à trancher explicitement dans le rapport

| # | Conflit | Source de vérité retenue | Traitement rédactionnel |
|---|---|---|---|
| C-01 | Le cahier des charges (mai 2026) décrit trois modules métier (auth, offres, candidatures) et un back-office de base. L'implémentation comporte en outre : notation IA, rapprochement sémantique, assistant CAG, entretiens avec visioconférence, tests techniques, négociation salariale, contrats et signature électronique, budget, employés, carrière, rapports, notifications temps réel. | **Implémentation** | Présenter le cahier des charges comme la base approuvée, puis documenter l'extension de périmètre comme une contribution, en la datant. `TODO: faire confirmer que l'extension a été approuvée.` |
| C-02 | Rôles : le cahier des charges en décrit 3 (+ visiteur) ; le code en définit 4 (`ADMIN`, `RH`, `RECRUTEUR`, `CANDIDAT`) avec héritage Casbin `RECRUTEUR → RH → ADMIN`. | **Implémentation** (`backend/app/models/user.py`, `core/rbac_policy.csv`) | Documenter l'évolution du modèle de rôles comme une décision, avec son motif (lisible dans la docstring de `UserRole`). |
| C-03 | Versions : cahier des charges et `DOCUMENTATION.md` annoncent « Angular 17+ » et « Python 3.11+ ». Les manifestes donnent Angular **19.2.x** (`frontend/package.json`) et Python **3.14** (`.github/workflows/ci.yml`, `backend/Dockerfile`, `requirements.txt`). | **Manifestes** | N'écrire que les versions des manifestes, avec leur date de relevé. |
| C-04 | `DOCUMENTATION.md` §2 affirme que le schéma est créé au démarrage par `Base.metadata.create_all`. `backend/app/main.py` ne crée plus rien : il **vérifie** que la base porte la révision Alembic de tête et journalise une erreur en cas d'écart. | **Code** | Documenter le passage à Alembic comme source unique du schéma (commit « Phase 1.1 ») et corriger la documentation. |
| C-05 | `backend/scripts/train_salary_model.py` annonce en docstring un format `piqbit_salary_v2` ; l'artefact livré porte `format = "piqbit_salary_v3"`. | **Artefact** (lu le 2026-09-22) | Citer `v3`. **Résolu le 2026-10-03** : l'ancien script a été retiré ; `scripts/salary_ml_pipeline.py` est désormais le seul script d'entraînement, et il écrit `v3`. Il n'y a plus de dette documentaire à signaler. |
| C-06 | NFR du cahier des charges : « taille bundle frontend < 500 Ko (compressé ~106 Ko) ». Mesure du 2026-09-22 : **1,25 Mo brut / 246,82 ko transférés** pour le bundle initial, avec dépassement de budget signalé par le compilateur. | **Mesure datée** | Exigence **non satisfaite** : à porter en résultat de validation et en limitation, pas à masquer. |
| C-07 | NFR du cahier des charges : disponibilité « 99,5 % minimum en production ». Aucun environnement de production, aucune mesure. | **Absence de preuve** | À déclarer explicitement non vérifiée, hors périmètre de l'évaluation. |
| C-08 | **Deux plannings prévisionnels incompatibles.** Le cahier des charges §11 découpe le projet en **9 phases fonctionnelles** (Setup, Auth, Offres, Candidatures, Profil, Backoffice, UI/UX, Tests, Déploiement). `generate_gantt.py` — qui produit `gantt_diagram.png`, la seule figure de planning disponible — en décrit **5, techniques** (Planification/Setup, Backend, Frontend, Intégration/Tests, Déploiement). Ni le nombre, ni les intitulés, ni le découpage ne coïncident. | **Aucune des deux** n'est une preuve de déroulement | `TODO:` faire trancher lequel fait foi. En attendant, la figure est légendée « cinq phases » — ce qu'elle montre réellement — et l'écart est signalé. Ne jamais commenter le découpage en 9 phases en s'appuyant sur cette figure. |

---

## Constats de preuve

### Produit et problème

- Nom : **PIQBIT**.
- Catégorie : application web ATS multi-rôles avec services d'aide à la décision.
- Utilisateurs confirmés par le code : visiteur anonyme, candidat, recruteur, RH,
  administrateur (`backend/app/models/user.py`, `frontend/src/app/app.routes.ts`).
- Situation existante : `TODO: M-09`.
- Problématique : `TODO: M-09`.
- Contribution proposée : `TODO: M-09` — les briques techniques sont établies,
  mais leur mise en récit comme réponse à un problème constaté exige le contexte
  du commanditaire.
- Contraintes confirmées (cahier des charges §10) : CV en PDF/DOC/DOCX, 5 Mo
  maximum (**vérifié dans le code** : `backend/app/services/cv_storage.py`,
  `ALLOWED_EXTENSIONS`, `MAX_SIZE_BYTES = 5 * 1024 * 1024`) ; une candidature par
  offre ; interface en français ; stockage des fichiers sur système de fichiers
  local ; serveur SMTP requis pour la vérification d'adresse.
- Exclusions constatées : observabilité, hébergement, tests non fonctionnels.

### Périmètre fonctionnel

| Domaine fonctionnel | Comportement confirmé | Acteurs | Preuve |
| --- | --- | --- | --- |
| Authentification et comptes | Inscription, connexion, jeton d'accès + de rafraîchissement, OAuth Google, vérification d'adresse par code à usage unique, mot de passe oublié/réinitialisation, changement de mot de passe, 2FA TOTP avec codes de secours, déconnexion. 15 routes. | Tous | `backend/app/api/v1/endpoints/auth.py`, `core/security.py` |
| Autorisation | 4 rôles, héritage `RECRUTEUR → RH → ADMIN`, politique externalisée ; toute permission absente est refusée. | Système | `core/rbac.py`, `core/rbac_policy.csv`, `core/rbac_model.conf`, garde `permissionGuard` côté Angular |
| Offres d'emploi | CRUD, recherche, offres similaires, extraction d'offre depuis texte libre, pondérations de notation portées par l'offre. | Visiteur, candidat, recruteur, RH, admin | `endpoints/recruitment.py`, `agents/job_extraction_agent.py` |
| Candidatures et CV | Candidature avec dépôt de CV, CV de profil, aperçu et téléchargement, retrait de candidature, suppression avec nettoyage, export CSV, offres sauvegardées, recommandation d'offres au candidat. | Candidat, recruteur, RH, admin | `endpoints/recruitment.py`, `services/cv_storage.py`, `services/recommendation_service.py` |
| Analyse de CV | Extraction de texte (PDF/DOCX), extraction de compétences, d'expérience et de formation. | Système | `services/cv_parser.py`, `services/nlp_service.py` |
| Notation des candidats | Score pondéré compétences / expérience / formation, pondérations par défaut 0,5 / 0,3 / 0,2 normalisées, surchargeables par offre ; analyse unitaire ou en lot ; classement par offre ; détail du score exposé au candidat. | Recruteur, RH, admin, candidat (son propre détail) | `services/scoring_service.py`, `endpoints/scoring.py` |
| Rapprochement sémantique | Indexation des offres et des CV en vecteurs de dimension 384 ; recherche par distance cosinus via pgvector + index HNSW, **avec repli Python** quand l'extension est absente. | Recruteur, RH, admin | `services/semantic_service.py`, `services/embedding_service.py`, migration `9b1c4d2e7f30_pgvector_native_search.py` |
| Assistant CAG | Question/réponse **extractive** sur base de connaissances et passages de CV, sans appel à un LLM ; renvoie le passage source, sa citation et un score de confiance. | RH, admin | `services/cag_service.py`, `endpoints/cag.py` |
| Entretiens | Invitations, créneaux, confirmation publique par jeton, synchronisation Google Calendar optionnelle, lien de visioconférence (Google Meet si délégation disponible, sinon salle Jitsi dérivée du jeton), rappel « rejoindre maintenant », évaluation d'entretien, balayage des invitations expirées. | Recruteur, RH, admin, candidat | `services/interview_service.py`, `endpoints/interview.py`, `app/main.py` |
| Test technique | Vivier de questions, génération, envoi, passage par lien public à jeton, correction et relecture ; éligibilité calculée **côté serveur** à partir d'un score de CV minimal. | RH, admin, candidat | `endpoints/assessment.py`, `services/assessment_service.py` |
| Négociation salariale | Rounds persistés, analyse d'écart demande/marché, canal WebSocket, prédiction de fourchette par modèle ML avec repli heuristique. | RH, admin | `services/negotiation_analysis_service.py`, `negotiation_repository.py`, `salary_prediction_service.py`, routeur monté séparément dans `app/main.py` |
| Contrats et intégration | Génération de contrat depuis une candidature, envoi, signature électronique auto-hébergée par lien public à jeton (tracé manuscrit sur canvas, empreinte SHA-256 des termes, piste d'audit, certificat en page dédiée du PDF), activation créant la fiche employé. | RH, admin, candidat | `services/contract_service.py`, `services/contract_pdf.py`, `endpoints/contracts.py` |
| RH interne | Employés, budgets par département et dépenses, plans de carrière. | RH, admin | `endpoints/employees.py`, `budget.py`, `career.py` |
| Rapports et décision | Synthèse de recrutement, instantanés archivés, export PDF, évaluation d'offre et recommandation. | RH, admin | `endpoints/reports.py`, `decision.py`, `services/report_service.py` |
| Notifications | Notifications en base + diffusion temps réel par WebSocket authentifié par jeton. | Tous les rôles connectés | `endpoints/notifications.py`, `services/notification_ws.py` |
| Journalisation d'audit | Table `audit_logs` : acteur, action, ressource, détails, adresse IP, agent utilisateur, horodatage. | Système | `backend/app/models/user.py` |

Volumétrie relevée le 2026-09-22 : **18 modules d'endpoints** agrégés sous
`/api/v1` plus le routeur de négociation monté séparément ; **173 décorateurs de
route** ; **2 points d'entrée WebSocket** (notifications, négociation) ;
**25 tables**, **18 révisions Alembic**.

`TODO:` critères d'acceptation formels au-delà de ceux du cahier des charges §4.

### Architecture et pile technique

| Capacité | Responsabilité | Implémentation vérifiée | Preuve |
| --- | --- | --- | --- |
| Client | SPA : site carrière public, espace candidat, back-office ; routes différées pour les modules lourds ; gardes d'authentification et de permission | Angular **19.2.x**, TypeScript **5.7.x**, RxJS 7.8, Angular Material/CDK 19.2, Chart.js 4.5 | `frontend/package.json` (2026-09-22) |
| API applicative | API REST JSON + WebSocket, validation d'entrée/sortie, règles métier | FastAPI **0.136.1**, Starlette 1.0.0, Uvicorn 0.49.0, Pydantic **2.13.4** / pydantic-settings 2.14.0, Python **3.14** | `backend/requirements.txt`, `backend/Dockerfile`, `.github/workflows/ci.yml` |
| Stockage autoritatif | Données métier relationnelles | PostgreSQL **16** via image `pgvector/pgvector:pg16`, SQLAlchemy **2.0.50** en asynchrone (`asyncpg` 0.31.0), migrations Alembic **1.18.4** | `docker-compose.yml`, `backend/alembic/` |
| Recherche vectorielle | Similarité sémantique indexée | Extension `vector` + index HNSW sur colonne `vec`, **repli Python** sur vecteurs JSON | `services/semantic_service.py`, migration `9b1c4d2e7f30` |
| Cache et limitation de débit | Compteurs anti-force brute, limitation par route | Redis **7** (client `redis` 8.0.0) | `docker-compose.yml`, `backend/app/cache/` |
| Identité et accès | Authentification et autorisation | JWT HS256 (`python-jose`), bcrypt 5.0.0 (12 tours), TOTP (`PyOTP` 2.10.0), OAuth Google, **Casbin 1.43.0** pour l'autorisation | `core/security.py`, `core/rbac.py`, `core/config.py` |
| Traitement documentaire | Extraction de texte des CV | `pdfplumber` 0.11.9 / `pdfminer.six`, `python-docx` 1.2.0 | `services/cv_parser.py` |
| Représentations vectorielles | Encodage des textes | `sentence-transformers` 5.6.0, modèle `paraphrase-multilingual-MiniLM-L12-v2`, dimension **384**, `torch` 2.13.0 **en variante CPU** ; **repli par hachage déterministe** quand le modèle est indisponible | `core/config.py`, `services/embedding_service.py`, `backend/Dockerfile` |
| Apprentissage automatique | Prédiction de fourchette salariale | `scikit-learn` 1.9.0 ; artefact `salary_model_piqbit.p`, format `piqbit_salary_v3`, `MultiOutputRegressor(GradientBoostingRegressor)` | Lecture de l'artefact le 2026-09-22 |
| LLM externe | Optionnel, dégradation gracieuse | Clients Anthropic et Google Gemini **facultatifs** ; sans clé, les fonctions concernées se replient | `core/config.py`, `backend/app/integrations/` |
| Exécution et publication | Conteneurs et service statique | Docker multi-étapes ; `python:3.14-slim` (utilisateur non privilégié `piqbit`, `HEALTHCHECK`) ; `node:22-alpine` → `nginx:1.27-alpine` | `backend/Dockerfile`, `frontend/Dockerfile` |
| Entrée réseau | Origine unique, proxy API et WebSocket | nginx : `/api/` → `backend:8000`, bloc WebSocket dédié, gzip, en-têtes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `client_max_body_size 25m` | `frontend/nginx.conf` |
| Observabilité | Journalisation et sonde de vie | `logging` de la bibliothèque standard configuré au démarrage ; `GET /health` ; `HEALTHCHECK` des deux images ; table `audit_logs` | `app/main.py`, Dockerfiles |

Interaction principale confirmée :

```text
Navigateur (candidat | recruteur | RH | admin)
  -> nginx (origine unique : fichiers statiques Angular + proxy /api/)
  -> FastAPI /api/v1 (validation Pydantic, dépendance d'authentification JWT,
                      autorisation Casbin)
  -> couche service (recruitment, scoring, nlp, cv_parser, semantic,
                     salary_prediction, contract, interview, notification…)
  -> PostgreSQL 16 (+ pgvector)  |  Redis 7  |  système de fichiers (uploads)
  -> dépendances externes OPTIONNELLES : SMTP, Google Calendar, Anthropic,
     Gemini, Hugging Face — chacune avec un repli documenté
  -> réponse JSON, ou poussée WebSocket (notifications, négociation)
```

### Infrastructure et déploiement

- Modèle d'hébergement : **aucun environnement cible**. Ce qui existe est une
  pile conteneurisée exécutable localement (`docker compose --profile app up -d
  --build`). `TODO: cible d'hébergement.`
- Environnements : développement local ; runner GitHub Actions pour la CI.
  Aucun environnement de recette ni de production. Aucune stratégie de promotion.
- Empaquetage : images Docker multi-étapes, backend et frontend.
- Orchestration : Docker Compose. **Non applicable** : orchestrateur de cluster.
- Réseau et entrée : nginx en origine unique, port hôte 8080 ; TLS **absent**
  (`listen 80`). `TODO: terminaison TLS.`
- Configuration : `pydantic-settings`, variables d'environnement, `.env` non
  suivi, `backend/.env.example` documenté et committé.
- Gestion des secrets : **par fichier `.env` local et variables d'environnement**.
  `backend/.gitignore` exclut `.env`, `*.json` et `google-calendar-sa.json`.
  Aucun coffre à secrets. `HF_TOKEN` est typé `SecretStr` pour ne pas fuiter
  dans un `repr()` ou une trace.
- Persistance : volumes Docker nommés `pg-data`, `redis-data`, `uploads`.
- Montée en charge et résilience : `restart: unless-stopped`, sondes de santé
  des conteneurs, `depends_on: service_healthy`. **Aucune limite mesurée** ;
  aucun test de charge ni de bascule.
- Sauvegarde et restauration : `TODO:` — des empreintes locales existent sous
  `backend/backups/` (exclues du dépôt), mais **aucune procédure écrite ni
  restauration éprouvée**.

### Livraison et DevOps

- Gestion de version : Git, branche `main`. Historique **court et discontinu** :
  21 commits, du 2026-07-08 (« initial clean commit ») au 2026-09-15.
  `TODO: M-11` — ne rien revendiquer sur la méthode de développement à partir
  de cet historique.
- Intégration continue : GitHub Actions, `.github/workflows/ci.yml`,
  déclenchée sur `push` et `pull_request` vers `main`/`master`, annulation des
  exécutions concurrentes, deux tâches parallèles.
- Portes configurées :
  1. **Contrôle de dérive du schéma** — `alembic upgrade head`, puis
     `alembic revision --autogenerate` sur une base à jour ; la présence d'une
     opération de schéma dans la révision générée fait échouer la tâche.
  2. **Suite de tests backend** — `pytest -q --no-header`, avec services
     PostgreSQL `pgvector/pgvector:pg16` et Redis 7.
  3. **Build de production Angular** — échoue sur toute erreur de typage.
  4. **Tests unitaires frontend** — Karma / ChromeHeadless.
- Flux d'artefact : les images Docker sont **construites localement ou au
  déploiement** ; la CI **ne publie aucune image** dans un registre.
- Déploiement et promotion : **aucun** dans la CI. Le conteneur backend applique
  `alembic upgrade head` à son démarrage.
- Stratégie de retour arrière : `TODO:` — aucune procédure documentée.
- Analyse statique dédiée (typage Python, lint) : **absente** de la CI. Le
  typage Python n'est pas vérifié automatiquement.
- Analyse de dépendances ou de secrets : **absente**.

### Constats de sécurité

- Authentification : mot de passe haché bcrypt à 12 tours ; politique de force
  du mot de passe ; jetons JWT HS256, accès 30 min / rafraîchissement 7 j ;
  champ `tokens_valid_from` permettant l'invalidation en masse (migration
  `c4d7a2e51f88`) ; OAuth Google ; 2FA TOTP avec codes de secours hachés ;
  vérification d'adresse par code à usage unique, durée et nombre de tentatives
  plafonnés **par compte**.
- Défense contre la force brute : compteur par IP **et** verrouillage de compte
  (5 tentatives, 15 min) ; limitation de débit séparée sur `register`,
  `forgot-password`, jetons, `login`, `refresh`, TOTP, renvoi de code.
- Égalisation de latence : un hachage factice est calculé lorsque le compte
  n'existe pas, pour ne pas révéler l'existence d'une adresse par le temps de
  réponse (`core/security.py`).
- Autorisation : Casbin, politique déclarative en CSV, refus par défaut,
  héritage de rôles ; garde de permission côté Angular **en complément** — la
  décision reste serveur.
- Frontières de confiance : navigateur ↔ nginx ↔ API ↔ base ; **liens publics à
  jeton** pour la confirmation d'entretien, le passage de test et la signature
  de contrat — ces jetons tiennent lieu d'authentification et constituent une
  frontière à documenter explicitement au chapitre 3.
- Protection des données : les CV déposés vivent sous `backend/uploads/`,
  **exclus du dépôt** avec un motif écrit (données personnelles réelles) ;
  `backend/backups/` également exclu.
- CORS : piloté par configuration, liste d'origines ; `ALLOW_LOCALHOST_ORIGINS`
  doit valoir `false` en production, ce que la composition Docker impose déjà.
- En-têtes de sécurité : `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` posés par nginx. **Absents** : HSTS, CSP.
- Dépôt de fichiers : liste blanche d'extensions et de types MIME, plafond 5 Mo.
- Auditabilité : table `audit_logs`.
- Limitations : **pas de TLS** dans la composition fournie ; pas d'analyse de
  dépendances ; pas de coffre à secrets ; **aucun test de sécurité dynamique** ;
  une clé de compte de service Google (`backend/google-calendar-sa.json`) est
  présente sur le poste — exclue du dépôt, **à ne jamais reproduire dans le
  rapport**.

### Constats d'observabilité

- Métriques : **non implémentées**.
- Journaux : journalisation standard vers la sortie, niveau piloté par
  `LOG_LEVEL`, format horodaté. Aucune agrégation, aucun format structuré JSON.
- Traces : **non implémentées**.
- Tableaux de bord d'exploitation : **non implémentés**. (Les tableaux de bord
  de l'application sont des vues métier, pas de la télémétrie.)
- Alertes : **non implémentées**.
- Sondes de santé : `GET /health` ; `HEALTHCHECK` sur les deux images.
- Propriété opérationnelle : `TODO:`.

Le rapport ne doit revendiquer **aucune** observabilité de bout en bout.

### Constats de test et de validation

Vocabulaire d'états imposé par `validation_evidence_inventory.md`. Résultats
détaillés et datés : `validation_runs/2026-09-22_validation_summary.md`.

| Domaine | Méthode | État de preuve | Résultat et limite |
| --- | --- | --- | --- |
| Build frontend | `npm run build -- --configuration production` | **Captured pass** (2026-09-22) | Succès en 36,0 s. 4 avertissements de budget, dont le bundle initial : 1,25 Mo brut / 246,82 ko transférés contre un budget de 800 ko. Le succès du build vaut aussi vérification de typage TypeScript strict. |
| Tests backend | `pytest -q --no-header`, SQLite sur fichier, backend d'embedding `hash` | **Captured failure** (2026-09-22) | 594 réussis, **3 échoués**, 6 ignorés, en 607,4 s ; code de sortie `1`. Détail et analyse des trois échecs dans `validation_runs/2026-09-22_validation_summary.md`. |
| Build backend / image Docker | `backend/Dockerfile` | **Implementation confirmed; execution not captured** | Aucune construction d'image capturée à cette date. |
| Analyse statique | — | **Not applicable** (absente du projet) | Aucun outil de typage ou de lint configuré en CI. Le build Angular couvre le typage TypeScript ; **rien ne couvre le typage Python**. |
| Tests d'intégration | Inclus dans la suite `pytest` via client ASGI `httpx` | Couverts par la campagne du 2026-09-22 | Les tests traversent API → service → base **SQLite**, pas PostgreSQL : le chemin `pgvector` natif n'est pas couvert localement. |
| Tests unitaires frontend | `npm test` (Karma, ChromeHeadless), 39 fichiers `.spec.ts` | **Planned** à cette date | Non exécutés dans cette campagne. |
| Tests de bout en bout | — | **Planned** | Aucun harnais E2E dans le dépôt. |
| Tests de sécurité | Tests fonctionnels d'authentification et de RBAC (`test_auth_security.py`, `test_rbac.py`) | Couverts par la suite `pytest` | **Aucun test dynamique** (scan, fuzzing, revue d'intrusion). La campagne du 2026-09-22 a mis au jour une **incohérence d'autorisation réelle** (échec E-03) sur `start-negotiation`. |
| Tests de performance | — | **Planned** | Aucune mesure de latence ni de charge. La NFR « < 2 s » du cahier des charges reste **non vérifiée**. |
| Tests de résilience | — | **Planned** | Aucun test de panne, de bascule ni de restauration. |
| Préparation au déploiement | Composition Docker + migrations au démarrage | **Implementation confirmed; execution not captured** | Aucun démarrage de pile complète capturé à cette date. |

### Preuves d'interface

| Objectif utilisateur | Vue ou parcours | Actif de preuve | Redaction | Usage prévu |
| --- | --- | --- | --- | --- |
| Découvrir et postuler | Site carrière, détail d'offre, modale de candidature | `TODO:` aucune capture | **Non applicable — actif inexistant** | Chapitre 4 |
| Suivre sa candidature | Mes candidatures, détail du score | `TODO:` | — | Chapitre 4 |
| Classer les candidats | Back-office recrutement, `candidate-ranking`, `score-breakdown` | `TODO:` | — | Chapitre 4 |
| Planifier un entretien | `interview-manager`, confirmation publique | `TODO:` | — | Chapitre 4 |
| Négocier un salaire | Page négociation, journal temps réel | `TODO:` | — | Chapitre 4 |
| Signer un contrat | Page publique de signature, PDF + certificat | `TODO:` | — | Chapitre 4 |
| Exécuter la CI | Résumé d'exécution GitHub Actions | `TODO:` | — | Chapitre 5 |

**Règle de capture pour ce projet** : toutes les captures devront être prises
sur un jeu de **données de démonstration** (`backend/scripts/seed_demo.py`).
`backend/uploads/` contient 264 CV réels et ne doit apparaître ni à l'écran, ni
dans une arborescence, ni dans un journal.

---

## Ce qui ne doit pas figurer dans le rapport

- Contenu, résultats, captures, bibliographie ou choix techniques d'un autre projet.
- Valeurs de `backend/.env`, `backend/google-calendar-sa.json`, empreintes de
  `backend/backups/`, contenu de `backend/uploads/`, bases `test_*.db`.
- Le nom du gérant et le matricule fiscal présents en valeurs par défaut dans
  `backend/app/core/config.py`, sauf accord explicite (M-14).
- L'adresse électronique de l'autrice figurant dans le cahier des charges.
- Chemins absolus du poste de travail (`E:\PIQBIT\…`) dans les extraits, journaux
  et captures.
- Toute affirmation de disponibilité, de performance, de scalabilité ou de
  conformité : aucune n'est mesurée.

---

## Structure de rapport retenue

Cinq chapitres, conformément à la recommandation de `pfe_report_spec_refined.md`,
avec introduction et conclusion générales. Le détail section par section, avec
les preuves rattachées, est dans `05_report_plan.md`.

Organisation du chapitre 4 : **par sous-système**, et non par sprint. Motif
consigné : l'historique Git ne documente pas un déroulement itératif
(M-11), et `pfe_latex_conventions.md` interdit d'imposer un vocabulaire de
sprint que le projet n'a pas suivi.

---

## Compilation et reproductibilité

- Commande de compilation principale : `latexmk -pdf main.tex`
  (`TODO:` à réconcilier avec le gabarit institutionnel, M-03).
- Distribution TeX et version : `TODO:` — aucune installation TeX vérifiée sur
  ce poste à ce jour.
- Processeur bibliographique : `TODO: M-07`.
- Outils externes de diagramme : `TODO:` — aucun diagramme source n'existe
  encore dans le dépôt.
- Révision du gabarit : `TODO: M-03`.
- Options sensibles (`-shell-escape`) : aucune à ce stade ; à éviter.

---

## Entrées encore manquantes

Voir `00_missing_information.md`. Résumé : M-01 à M-08 (métadonnées et gabarit),
M-09 à M-12 (contexte et méthode), M-13 à M-15 (autorisations), M-16 (gabarit de
campagne reconstitué).

---

## Liste de contrôle avant rédaction des chapitres

- [x] Faits techniques confirmés ou marqués `TODO`.
- [x] Sources de preuve datées ou révisionnées.
- [x] Conflits entre sources explicités (C-01 à C-07) avec source de vérité retenue.
- [x] Mécanismes implémentés distingués des exécutions capturées.
- [x] Vocabulaire d'états de preuve respecté.
- [x] Une campagne de validation datée existe.
- [ ] Traçabilité exigence → implémentation → test complète (`02_evidence_inventory.md`, partielle).
- [ ] Figures, tableaux et captures produits et référencés.
- [ ] Secrets et données personnelles absents des actifs **finaux** (règle posée, actifs non encore produits).
- [ ] Bibliographie constituée et vérifiée.
- [ ] Métadonnées académiques confirmées (M-01 à M-08).
