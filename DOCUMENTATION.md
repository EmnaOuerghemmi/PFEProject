# 📘 Documentation PIQBIT — Plateforme de Recrutement (V1)

> Document de livraison V1 — couvre l'architecture, les modules implémentés dans
> cette itération, l'API, l'installation, l'exécution et les tests.
> Dernière mise à jour : 2026-06-14.

---

## 1. Présentation

PIQBIT est une plateforme web de recrutement (ATS) augmentée d'un volet IA :
- **Frontoffice (candidat)** : consultation d'offres, candidature avec CV, suivi,
  offres sauvegardées, profil.
- **Backoffice (RH / Admin)** : gestion des offres et candidatures, tableau de
  bord, recrutement intelligent (scoring IA des CV), entretiens, négociation
  salariale automatique, carrière, rapports.

### Stack technique

| Couche | Technologie |
|---|---|
| Frontend | Angular 17+ (standalone components), TypeScript strict, RxJS |
| Backend | FastAPI (Python 3.11+), async/await |
| ORM / DB | SQLAlchemy (async) + PostgreSQL |
| Auth | JWT (access + refresh), bcrypt, 2FA TOTP, Google OAuth |
| Cache | Redis |
| IA / ML | NLP (extraction CV), scoring pondéré, prédiction salaire (ML + fallback heuristique), intégration Claude optionnelle |
| Temps réel | WebSocket (négociation) |

---

## 2. Architecture

```
E:\PIQBIT
├── backend/
│   └── app/
│       ├── main.py                 # bootstrap FastAPI + montage routeurs + lifespan
│       ├── core/                   # config, sécurité (JWT/bcrypt), dépendances RBAC
│       ├── db/                     # session async, base déclarative, init superadmin
│       ├── models/                 # SQLAlchemy : user, recruitment, scoring, interview,
│       │                           #              career, report
│       ├── schemas/                # Pydantic (validation entrées/sorties)
│       ├── services/               # logique métier (recruitment, scoring, nlp, cv_parser,
│       │                           #   salary_prediction, decision, career, analytics, email…)
│       ├── agents/                 # agents IA (scoring, decision/negotiation, analyzer,
│       │                           #   recommendation, report_generator, monitoring)
│       ├── integrations/           # claude_client (Anthropic, optionnel)
│       └── api/v1/
│           ├── router.py           # agrège les routeurs sous /api/v1
│           └── endpoints/          # auth, agents(users), recruitment, scoring, workflow,
│                                   #   interview, dashboard, career, reports, decision,
│                                   #   negotiations (monté directement)
└── frontend/
    └── src/app/
        ├── core/                   # services (api, auth, recruitment, user, career…),
        │                           #   guards (auth/admin), interceptors (jwt), models
        ├── features/
        │   ├── auth/               # login, register, forgot/reset password, verify email
        │   ├── frontoffice/        # job-list, job-detail, my-applications, saved-jobs, profile
        │   └── backoffice/         # dashboard, jobs-management, applications, users-management,
        │                           #   recruitment, interview-manager, career, negotiation
        ├── services/               # negotiation.service (WebSocket)
        └── shared/components/      # candidate-ranking, cv-analysis, score-breakdown,
                                    #   interview-scheduler, pagination, kpi-card…
```

Communication : SPA Angular ↔ API REST FastAPI en HTTP/JSON sécurisé par JWT
(Bearer). Le WebSocket de négociation est exposé sur `ws://…/api/v1/negotiations/ws/{jobId}`.

Création du schéma : au démarrage, `Base.metadata.create_all` crée les tables
manquantes (les nouveaux modèles `career_plans`, `saved_jobs`, `report_snapshots`
sont créés automatiquement). Un superadmin est initialisé au boot.

---

## 3. Modèle de données (ajouts V1)

| Table | Rôle |
|---|---|
| `saved_jobs` | offres sauvegardées par un utilisateur (unique `user_id`+`job_offer_id`) |
| `career_plans` | plans de carrière des employés (statut, progression, poste cible) |
| `report_snapshots` | snapshots archivés des rapports de recrutement (JSON) |

Tables préexistantes : `users`, `audit_logs`, `job_offers`, `candidates`,
`applications`, `cv_analyses`, `candidate_scores`, `interview_invitations`,
`interview_slots`.

---

## 4. Fonctionnalités livrées dans cette itération

| Gestion | Fonctionnalité | Backend | Frontend |
|---|---|---|---|
| Candidatures | **CAND-08** Suppression candidature + nettoyage CV/scores/entretiens | `DELETE /recruitment/applications/{id}` (Admin) | bouton « Supprimer » réel (applications backoffice) |
| Offres | **PUT** /jobs/{id} (mise à jour complète) | `PUT /recruitment/jobs/{id}` (RH/Admin) | `recruitment.service.replaceJob()` |
| Profil | Zone Danger : suppression compte + changement MDP + sauvegarde réelle | `DELETE /users/me` | profil câblé (deleteMe / changePassword / updateMe) |
| Front Office | Offres sauvegardées (bout-en-bout) | modèle `saved_jobs` + `GET/POST/DELETE /recruitment/saved-jobs` | page saved-jobs réelle + bouton « Sauvegarder » sur le détail d'offre |
| Front Office | « Postuler » depuis saved-jobs | — | navigation vers le détail de l'offre |
| Recrutement IA | Page `/admin/recruitment` câblée au scoring | `POST /recruitment/jobs/{id}/analyze-all`, ranking | sélecteur d'offre + « Analyser tous les CV » + `candidate-ranking` (scores, compétences, recommandation) + KPIs rapports |
| Négociation | Routeur monté + WebSocket + UI | `negotiations.router` monté (`/api/v1/negotiations/*` + WS) | page `/admin/negotiation` fonctionnelle (formulaire + journal temps réel WS) |
| Négociation | Prédiction salaire sans modèle | **fallback heuristique** dans `salary_prediction_service` | — |
| Carrière | Module complet | modèle + service + `GET /career/stats`, `GET/POST/PATCH/DELETE /career/plans` | page `/admin/career` (KPIs réels + table des plans) |
| Rapports | Module monté | `GET /reports/recruitment-summary`, snapshots | KPIs affichés dans la page Recrutement |
| Décision | Module monté | `POST /decision/evaluate-offer`, `GET /decision/applications/{id}/recommendation` | — (API exposée) |
| Agents IA | Scaffolding complété | `base_agent`, `analyzer`, `recommendation`, `report_generator`, `monitoring` | — |
| Claude/LLM | Intégration optionnelle | `integrations/claude_client` (dégradation gracieuse si pas de clé) | — |
| Export | Export CSV des candidatures | `GET /recruitment/applications/export` (RH/Admin) | bouton « Exporter CSV » (applications backoffice) |
| Transverse | Erreurs upload détaillées | validation type/taille (+ fallback extension) | messages d'erreur explicites (0/400/401) |
| Transverse | Tests | tests endpoints + logique pure | build Angular (typecheck complet) |

---

## 5. Référence API (principaux endpoints)

Base : `http://localhost:8000/api/v1`

### Authentification — `/auth`
`POST /register` · `POST /login` · `POST /logout` · `POST /refresh` ·
`POST /verify-email` · `POST /forgot-password` · `POST /reset-password` ·
`POST /change-password` · `POST /google` · `POST /2fa/*`

### Utilisateurs — `/users`
`GET /me` · `PATCH /me` · **`DELETE /me`** (suppression compte) ·
`GET /users` (RH/Admin) · `POST /users` (Admin) · `PATCH /users/{id}` (Admin) ·
`DELETE /users/{id}` (Admin) · `GET /users/audit-logs`

### Recrutement — `/recruitment`
| Méthode | Endpoint | Accès |
|---|---|---|
| GET | `/jobs` (recherche, tri, pagination) | public |
| GET | `/jobs/{id}` | public |
| POST | `/jobs` | RH/Admin |
| PATCH | `/jobs/{id}` | RH/Admin |
| **PUT** | `/jobs/{id}` | RH/Admin |
| DELETE | `/jobs/{id}` | RH/Admin |
| POST | `/apply/{job_id}` (multipart CV) | authentifié |
| GET | `/my-applications` | authentifié |
| GET | `/applications` | RH/Admin |
| PATCH | `/applications/{id}` (statut) | RH/Admin |
| **DELETE** | `/applications/{id}` | Admin |
| **GET** | `/applications/export` (CSV) | RH/Admin |
| **GET/POST/DELETE** | `/saved-jobs[/{job_id}]` | authentifié |
| GET | `/cv-preview/{path}`, `/cv-download/{path}` | authentifié |

### Scoring IA — `/recruitment`
`POST /applications/{id}/analyze` · `POST /jobs/{id}/analyze-all` ·
`GET /applications/{id}/analysis` · `GET /applications/{id}/score` ·
`GET /jobs/{id}/ranking`

### Workflow — `/recruitment`
`POST /applications/{id}/schedule-interview` ·
`POST /applications/{id}/reject` · `POST /applications/{id}/start-negotiation`

### Carrière — `/career` (RH/Admin/Staff)
`GET /stats` · `GET /plans` · `POST /plans` · `PATCH /plans/{id}` · `DELETE /plans/{id}`

### Rapports — `/reports` (RH/Admin)
`GET /recruitment-summary` · `POST /snapshot` · `GET ` (liste) · `GET /{id}`

### Décision — `/decision` (RH/Admin)
`POST /evaluate-offer` · `GET /applications/{id}/recommendation`

### Négociation — `/api/v1/negotiations` (monté directement)
`POST /initiate` · `POST /process-counter-offer` · `GET /summary/{job_id}` ·
`WS /ws/{job_id}`

Documentation interactive : **`http://localhost:8000/docs`** (Swagger) et `/redoc`.

---

## 6. Sécurité & RBAC

- **JWT** Bearer obligatoire sur les routes protégées ; refresh automatique côté
  frontend (intercepteur) ; mots de passe hachés **bcrypt**.
- **Rôles** : `ADMIN`, `RH_MANAGER`, `RH_STAFF`, `READ_ONLY` (candidat). Les
  dépendances `require_role(...)` protègent les endpoints ; le superadmin passe
  toujours.
- **Suppression de compte** : soft-delete (`deleted_at`), révocation du refresh
  token ; le superadmin est protégé.
- **Fichiers CV** : whitelist PDF/DOC/DOCX, max 5 Mo, suppression du fichier
  lors de la suppression de la candidature.
- **CORS** restreint au frontend ; validation Pydantic sur toutes les entrées.

---

## 7. Volet IA

| Composant | Comportement |
|---|---|
| Extraction CV (`nlp_service`, `cv_parser`) | compétences, expérience, formation, mots-clés |
| Scoring (`scoring_service`) | score pondéré compétences/expérience/formation (poids par offre), ranking |
| Prédiction salaire (`salary_prediction_service`) | modèle ML pickle si présent ; **sinon fallback heuristique** (base + primes rôle/séniorité/compétences/rating) |
| Décision négociation (`decision_service`, `decision_agent`) | accept/contre-offre/reject selon ratio offre/prédiction, simulation de rounds, diffusion WebSocket |
| Agents (`agents/`) | analyzer, recommendation, report_generator, monitoring — chacun avec **fallback déterministe** |
| Claude (`integrations/claude_client`) | activé si `ANTHROPIC_API_KEY` défini ; sinon textes déterministes. SDK importé en lazy (jamais bloquant) |

> Aucune dépendance « dure » à un service externe : tout le volet IA fonctionne
> hors-ligne avec des fallbacks déterministes. Claude et le modèle ML salaire sont
> des améliorations optionnelles.

---

## 8. Installation & exécution

### Déploiement Docker (recommandé)

La pile complète — PostgreSQL (avec pgvector), Redis, API et frontend — se
lance en une commande depuis la racine du dépôt :

```powershell
copy backend\.env.example backend\.env   # puis renseigner SECRET_KEY
docker compose --profile app up -d --build
```

Application disponible sur **http://localhost:8080**.

nginx sert le frontend et proxifie `/api/` vers le backend : les deux partagent
donc la même origine. Aucune configuration CORS n'est nécessaire, et la même
image fonctionne sur n'importe quel domaine sans rebuild.

| Commande | Effet |
|---|---|
| `docker compose up -d` | Infrastructure seule (PostgreSQL + Redis) |
| `docker compose --profile app up -d --build` | Pile complète |
| `docker compose --profile app logs -f backend` | Journaux de l'API |
| `docker compose down` | Arrêt (les données sont conservées) |
| `docker compose down -v` | Arrêt **et suppression des données** |

> **Port PostgreSQL** : le conteneur est publié sur **5434**, pas 5432. De
> nombreux postes font tourner des services PostgreSQL Windows occupant déjà
> 5432 et 5433 ; sous Windows, plusieurs processus peuvent se lier au même
> port sans erreur, et l'application se retrouve alors connectée au mauvais
> serveur sans le signaler.

#### Avant une mise en production

1. **`SECRET_KEY`** — générer une valeur unique :
   `python -c "import secrets; print(secrets.token_urlsafe(64))"`
2. **`ALLOW_LOCALHOST_ORIGINS=false`** — déjà positionné dans le
   `docker-compose.yml`, à conserver.
3. **Nom de domaine + HTTPS** — placer un reverse-proxy TLS (Traefik, Caddy,
   ou nginx avec Let's Encrypt) devant le port 8080.
4. **Mot de passe PostgreSQL** — remplacer `root` dans `docker-compose.yml`.
5. **Sauvegardes** — planifier un `pg_dump` du volume `pg-data`.

### Prérequis (installation manuelle)
- Python 3.14 , Node.js 22+ , PostgreSQL 16+, Redis 7+.

### Backend
```powershell
cd E:\PIQBIT\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Configurer .env (partir de .env.example) : DATABASE_URL, SECRET_KEY, SMTP_*…
alembic upgrade head              # créer / mettre à jour le schéma
uvicorn app.main:app --reload --port 8000
```

### Frontend
```powershell
cd E:\PIQBIT\frontend
npm install
npm start            # ng serve → http://localhost:4200
# Build production :
npx ng build
```

Variables d'environnement frontend : `src/environments/environment.ts`
(`apiUrl`, **`wsUrl`** ajouté pour le WebSocket de négociation).

### Compte superadmin (seed au démarrage)
`emna.ouerghemmi@esprit.tn` / `123Emna?`

---

## 9. Tests

### Backend
- **Tests d'endpoints** (`tests/test_recruitment_extra.py`) : saved-jobs, PUT
  jobs, suppression candidature, suppression compte, carrière, rapports,
  décision, export — avec contrôle RBAC. S'exécutent via :
  ```powershell
  cd E:\PIQBIT\backend
  pytest -q
  ```
- **Tests de logique pure** (`tests/test_decision_logic.py`) : moteur de
  décision de négociation, exécutables sans dépendances :
  ```powershell
  python tests/test_decision_logic.py   # 4/4 PASS
  ```
- Tests existants : `test_auth.py`, `test_users.py`.

### Frontend
```powershell
cd E:\PIQBIT\frontend
npx ng build          # typecheck complet de tout le câblage (doit réussir)
npx ng test           # tests unitaires Karma/Jasmine
```

> État de validation à la livraison : `ng build` ✅ (bundle généré),
> compilation backend complète ✅, tests logique pure ✅ 4/4.
> Les tests d'endpoints nécessitent l'environnement Python complet (deps + DB).

---

## 9bis. Design system & UI/UX (premium)

PIQBIT utilise deux design systems cohérents partageant la même typographie :

- **Frontoffice** (candidat) : thème sombre teal/cyan « glassmorphism » (OKLCH),
  défini dans `src/styles.css` sous `.layout-wrapper`. Surfaces translucides
  (blur + saturation), rayons 18px, hover lift, dégradés émeraude/cyan sur les CTA.
- **Backoffice** (RH/Admin) : design system « premium dashboard » (inspiré
  Linear/Stripe/Notion) — canvas crème, navigation forest-teal, accent gold.
  Tous les **tokens** (`--c-*`, `--r-*`, `--s-*`, `--sh-*`, `--fs-*`, `--ease-*`)
  sont déclarés sur `.backoffice-wrapper` et héritent à tous les composants.

**Polish premium appliqué dans cette itération :**
- **Typographie** : chargement de **Inter** + **Plus Jakarta Sans** (utilisées par
  les tokens mais auparavant non chargées → fallback système). `index.html` :
  `preconnect` + `font-display=swap`. Titre corrigé (`PIQPIT` → `PIQBIT`).
- **Couche de base globale** (`styles.css`) : `box-sizing` universel, scroll
  fluide, **scrollbars custom**, **`:focus-visible`** accessible (anneau teal),
  **`::selection`** de marque, micro-interactions boutons (press), respect de
  `prefers-reduced-motion`.
- **Frontoffice** : rayons des cartes/inputs/boutons agrandis, glass raffiné
  (blur+saturate), **hover lift** sur les `job-card`, dégradés et ombres premium
  sur les CTA, inputs plus lisibles.
- **Harmonisation** des écrans ajoutés (Recrutement IA, Négociation, Carrière,
  Export) sur les tokens du design system (couleurs, rayons, ombres, focus gold)
  — suppression des couleurs « brutes ».
- **Auth** : login aligné sur la typo Inter + rayons modernisés.

Budgets respectés (`ng build` ✅, aucune alerte). `styles.css` ≈ 15 kB.

---

## 10. Reste-à-faire / évolutions futures (hors périmètre V1)

- ~~Modèle ML salaire entraîné~~ ✅ **livré** (V1.1) — voir §11.
- ~~Persistance des négociations en base~~ ✅ **livré** (V1.1) — voir §11.
- Pages frontend dédiées pour Rapports et Décision (API déjà disponibles).
- Internationalisation (FR/AR) et tests E2E.

---

## 11. Négociation persistée + modèle ML salaire (V1.1)

### 11.1 Persistance des négociations
Les négociations ne sont plus stockées en mémoire process : elles sont
persistées en base et auditables.

| Table | Rôle |
|---|---|
| `negotiations` | une négociation (job, candidat, offre initiale, salaire prédit, statut final, `rounds_count`) |
| `negotiation_rounds` | chaque échange (round) : `actor` (employer/candidate/system), `amount`, `decision`, `reason` |

- Modèles : `app/models/negotiation.py` (cascade `Negotiation` → `NegotiationRound`).
- Repository async : `app/services/negotiation_repository.py`
  (`create`, `add_round`, `finalize`, `get_latest_by_job`, `list`, `stats`, `to_summary`).
- `POST /api/v1/negotiations/initiate` persiste désormais la négociation et ses
  rounds (best-effort, sans bloquer la réponse temps réel).
- Nouveaux endpoints de lecture (auth requise) :
  `GET /api/v1/negotiations/history/{job_id}` (dernière négociation persistée + rounds),
  `GET /api/v1/negotiations/` (liste, filtre `status`, pagination),
  `GET /api/v1/negotiations/stats` (agrégats par statut).

### 11.2 Modèle ML de prédiction salariale (marché TN)
Le fallback heuristique est remplacé (quand le modèle est présent) par un
**Gradient Boosting** multi-sortie, retenu parmi huit candidats et entraîné sur
`backend/datasets/tunisia_it_salaries.csv`.

- Script d'entraînement, **unique** : `backend/scripts/salary_ml_pipeline.py` —
  audit, nettoyage (écrit `tunisia_salaries_clean.csv` et `audit_report.json`),
  construction des features, comparaison des modèles, livraison
  → sérialise `backend/salary_model_piqbit.p` au format `piqbit_salary_v3`
  (consommé par `SalaryPredictionService`).
- Features (54, identiques entraînement/inférence — construites par le module
  partagé `app/services/salary_features.py`) :
  `one-hot(catégorie, 11) + séniorité(1..4) + expérience(années) + amplitude d'expérience + multi-hot(compétences, 40)`.
  Le niveau d'études a été retiré : colinéaire avec la séniorité dans ce jeu de
  données, il surcotait de 53 % toute offre junior déclarant « niveau ingénieur ».
- Cibles : `salary_min_tnd`, `salary_avg_tnd`, `salary_max_tnd` (TND, mensuel
  brut) — le modèle rend une fourchette, pas un point.
- Sélection : MAE de test moyennée sur 5 partitions 60/20/20 indépendantes,
  stratifiées par catégorie × séniorité.
- Performance du modèle retenu : **MAE ≈ 402 ± 55 TND, R² ≈ 0.893**, contre
  1 494 TND pour la simple moyenne (184 lignes après audit, 185 brutes).
- Le service déclare le modèle qu'il sert, lu dans l'artefact et non écrit en
  dur : `model_type` (ex. `ml_gradient_boosting`) et `model_version`
  (ex. `piqbit_salary_v3`) dans la réponse de `POST /negotiations/predict-salary`.
- Réentraînement : `cd backend && python scripts/salary_ml_pipeline.py`.

### 11.3 Tests
```powershell
cd E:\PIQBIT\backend
pytest tests/test_negotiation_persistence.py tests/test_salary_model.py -v
```
- `test_negotiation_persistence.py` : repository (create/add_round/finalize/list/
  stats), cascade ORM, `to_summary`, RBAC (401), et intégration
  `POST /initiate` → `GET /history`.
- `test_salary_model.py` : construction des features, contrat
  entraînement→production (le pipeline produit exactement les colonnes de
  l'artefact servi), identité du modèle lue dans l'artefact, chargement du
  modèle par le service, prédictions TND réalistes, monotonicité séniorité.

> Dépendances ajoutées : `scikit-learn`, `numpy`, `pandas` (modèle) ;
> `aiosqlite`, `pytest`, `pytest-asyncio`, `httpx` (tests).

---

## 12. Budget par département + Employés (V1.2)

### 12.1 Gestion du budget par département
Nouveau module full-stack avec **données de démonstration insérées automatiquement**
au premier démarrage (seed idempotent dans le lifespan).

| Table | Rôle |
|---|---|
| `department_budgets` | enveloppe annuelle d'un département (unique `department`+`year`, TND) |
| `budget_expenses` | lignes de dépense (SALAIRES / RECRUTEMENT / FORMATION / OUTILS / AUTRE) |

- Backend : `app/models/budget.py`, `app/services/budget_service.py`,
  endpoints `GET /budget/stats` (KPIs + agrégats par département + **effectif
  croisé avec le module Employés**), CRUD `/budget/departments[/{id}]`,
  `/budget/departments/{id}/expenses`, `DELETE /budget/expenses/{id}`,
  `POST /budget/seed`. Accès **ADMIN / RH_MANAGER**.
- Frontend : page **`/admin/budget`** (lien sidebar « Budget ») — 4 KPI cards
  (alloué, dépensé, restant, taux global), table des départements avec barre
  d'utilisation colorée (vert < 70 %, orange < 90 %, rouge ≥ 90 %), ligne
  dépliable montrant le **détail des dépenses** + ajout/suppression de dépense
  inline. Service : `core/services/budget.service.ts`.

### 12.2 Module Employés (orphelin → complété)
Les composants `features/employees/*` existaient sans backend ni routes : ils
sont désormais **câblés bout-en-bout**.

- Backend : table `employees`, service + endpoints `GET/POST /employees`,
  `GET/PUT/DELETE /employees/{id}`, `POST /employees/seed` — réponses en
  **camelCase** (contrat du modèle Angular existant). Accès RH/Admin.
- Frontend : routes **`/admin/employees`** (liste avec filtres département/
  statut, avatars, badges de statut), `/admin/employees/new` et
  `/{id}/edit` (formulaire création/édition), `/{id}` (fiche détail + zone
  danger). Lien sidebar « Employés ». Design system backoffice respecté.
- **Seed** : 12 employés de démo (répartis sur 7 départements, salaires
  cohérents avec le dataset marché TN) insérés au premier démarrage.

### 12.3 Nettoyage de la dette frontend
Suppression des coquilles vides jamais routées ni référencées (doublons des
vraies pages backoffice) : `features/career/career-plan`,
`features/negotiation/*`, `features/recruitment/*` (doublon de
`shared/components/candidate-ranking`), `features/dashboard`.

### 12.4 Fiabilisation de la suite de tests
`tests/conftest.py` corrigé pour pytest-asyncio ≥ 1.x (une event loop par
test) : moteur SQLAlchemy de test en `NullPool` + fixture autouse qui
réinitialise le client Redis global par test. Élimine les échecs aléatoires
« RuntimeError: Event loop is closed » qui touchaient les tests d'endpoints.

### 12.5 Tests
```powershell
cd E:\PIQBIT\backend
pytest tests/test_budget_employees.py -v
```
Seed idempotent, agrégation des stats (dont headcount croisé), flux dépense
(ajout → stats à jour → suppression), CRUD employé camelCase, RBAC (401/403).

> Note build frontend : budget CSS `anyComponentStyle` relevé à 20 kB warn /
> 64 kB error dans `angular.json` (plusieurs composants préexistants — ex.
> jobs-management ≈ 59 kB — dépassaient déjà l'ancien seuil de 8 kB).

---

## 13. Pages Rapports & Décision (V1.3)

### 13.1 Agent de reporting (complété)
`app/agents/report_generator_agent.py` produit désormais un **rapport structuré**
`{ narrative, highlights[], recommendations[], generated_by }` :
- **Synthèse** rédigée (Claude si `ANTHROPIC_API_KEY` défini, sinon fallback déterministe) ;
- **Points clés** contextuels (backlog en attente, entretiens/négociations en cours,
  offre la plus attractive, qualité du vivier selon le score IA moyen) ;
- **Recommandations** actionnables (traiter le backlog, revoir le sourcing,
  archiver les offres dormantes…).

### 13.2 Backend Rapports — CRUD complet + PDF
| Méthode | Endpoint | Rôle |
|---|---|---|
| POST | `/reports/snapshot` | génère (via l'agent) et archive un rapport ; `{title}` optionnel |
| GET | `/reports?page=&page_size=` | **liste paginée** `{items,total,page,pages,page_size}` |
| GET | `/reports/{id}` | lecture unitaire |
| PATCH | `/reports/{id}` | **renommage** |
| DELETE | `/reports/{id}` | **suppression** |
| GET | `/reports/{id}/pdf` | **téléchargement PDF** (reportlab, hors-ligne) |

Le PDF (`app/services/pdf_service.py`) reprend la palette du design system :
KPIs, synthèse, points clés, recommandations, candidatures par statut, top offres.

### 13.3 Frontend
- **`/admin/reports`** (sidebar « Rapports ») : KPIs live, barre « 🤖 Générer le
  rapport » (titre optionnel), **table paginée** (composant `app-pagination`
  partagé), ligne dépliable (synthèse + points clés + recommandations + chips
  de statuts), **renommage inline**, **téléchargement PDF** (blob), suppression.
  Badge indiquant si le contenu vient de Claude ou de l'agent déterministe.
- **`/admin/decision`** (sidebar « Décision ») : recommandations d'embauche par
  candidat (sélecteur d'offre → ranking scoré → `HIRE / INTERVIEW / HOLD /
  REJECT` avec justification, bouton « Recommander tous ») + formulaire
  d'évaluation d'offre salariale (prédit / proposé / confiance → décision
  accepter / contre-offre / rejeter).
- Service : `core/services/report.service.ts`. Routes en lazy-loading.

### 13.4 Tests
```powershell
cd E:\PIQBIT\backend
pytest tests/test_reports_module.py -v
```
Agent (structure + insights contextuels), PDF valide (`%PDF-`), flux CRUD
bout-en-bout (génération → liste paginée → renommage → PDF → suppression),
mathématique de pagination (3 items / page_size 2 → 2 pages sans doublon), RBAC.

> Dépendance ajoutée : `reportlab` (génération PDF).

---

## 14. Gestion d'entretiens — calendrier réel (V1.4)

### 14.1 Existant conservé
- Vue **calendrier hebdomadaire** dans `/admin/interviews` (`GET /interview/calendar`,
  états RESERVED / PROPOSED / AVAILABLE).
- Fichier **.ics** envoyé au candidat dans l'email de confirmation.

### 14.2 Nouveautés
| Fonction | Détail |
|---|---|
| **Sync Google Calendar** | à la confirmation d'un créneau par le candidat, l'entretien est poussé automatiquement dans l'agenda Google configuré (événement avec rappels email J-1 + popup 30 min) ; à l'annulation, l'événement est supprimé. Best-effort : sans credentials, tout le flux continue (emails + ICS). |
| `GET /interview/google-status` | état de l'intégration (configurée ou non + raison) — affiché en badge dans l'UI |
| `POST /interview/invitations/{id}/sync-google` | (re)pousse manuellement un entretien confirmé (503 si non configuré, 409 si non confirmé) |
| `GET /interview/invitations/{id}/ics` | téléchargement du **.ics** côté RH (importable Google/Outlook/Apple sans API) |
| Modèle | colonne `google_event_id` sur `interview_invitations` (micro-migration auto au boot PostgreSQL) |

- Client : `app/integrations/google_calendar.py` (compte de service Google,
  REST v3, jamais bloquant — pattern identique au client Claude).
- UI (`/admin/interviews`) : badge « 📆 Google Calendar : connecté / non
  configuré » dans l'en-tête, boutons **ICS** et **Sync Google** sur chaque
  invitation confirmée (toast de feedback).

### 14.3 Activer Google Calendar — credentials requis
1. **Google Cloud Console** → créer un projet → activer l'API **Google Calendar**.
2. **Créer un compte de service** (IAM & Admin → Service Accounts) → générer
   une **clé JSON** et la télécharger (ex. `backend/google-calendar-sa.json` —
   à garder hors git).
3. **Partager l'agenda cible** avec l'email du compte de service
   (`xxx@yyy.iam.gserviceaccount.com`) avec le droit « Apporter des
   modifications aux événements », puis copier l'**ID de l'agenda**
   (Paramètres de l'agenda → « ID de l'agenda »).
4. `.env` :
   ```env
   GOOGLE_CALENDAR_CREDENTIALS_FILE=E:\PIQBIT\backend\google-calendar-sa.json
   GOOGLE_CALENDAR_ID=xxxxxxxx@group.calendar.google.com
   # Optionnel (Google Workspace + domain-wide delegation) :
   # GOOGLE_CALENDAR_IMPERSONATE=rh@votre-domaine.tn
   GOOGLE_CALENDAR_TIMEZONE=Africa/Tunis
   ```
> Sans Workspace/délégation, les invités ne sont pas ajoutés à l'événement
> (limitation Google des comptes de service) — le candidat reçoit de toute
> façon l'invitation .ics par email. Dépendance ajoutée : `google-auth`.

### 14.4 Tests
`tests/test_interview_calendar.py` : statut Google non configuré (dégradation),
sync → 503 sans credentials, téléchargement ICS (200 `text/calendar`, contenu
RFC 5545) et 409 si non confirmé, colonne `google_event_id`. Les tests de
dégradation (`test_google_status_unconfigured`,
`test_sync_google_503_when_unconfigured`) sont **skip automatiquement** si de
vrais credentials sont configurés dans l'environnement courant (`.env`) —
ils testent le chemin "non configuré", inapplicable une fois l'intégration
activée.

### 14.5 Bug corrigé — resync manuelle utilisait la mauvaise session DB
`POST /interview/invitations/{id}/sync-google` appelait `_sync_confirmed_to_google`
qui ouvrait **toujours** sa propre session (`AsyncSessionLocal`, la vraie base),
au lieu de réutiliser la session de la requête — correct pour l'appel en
`BackgroundTask` après confirmation candidat (le scope de requête peut déjà
être fermé), mais incorrect pour l'appel synchrone du endpoint de resync
manuelle, où la session de la requête doit être réutilisée. Corrigé :
`_sync_confirmed_to_google(invitation_id, db=None)` accepte maintenant une
session optionnelle — réutilisée si fournie (resync manuelle), sinon une
session dédiée est ouverte (background task). Régression détectée par la
suite de tests après activation des vrais credentials Google Calendar.

---

## 15. Notifications in-app + temps réel (V1.5)

### 15.1 Deux flux couverts
- **Candidat** : changement de statut de candidature, entretien planifié /
  confirmé / annulé, négociation salariale lancée.
- **RH → Admin** : toute action significative d'un compte `RH_MANAGER` /
  `RH_STAFF` notifie **tous les comptes ADMIN** — offre créée, statut de
  candidature changé, entretien planifié/annulé, employé ajouté, dépense
  budget ajoutée, plan de carrière créé, négociation lancée, rapport généré.
  Un admin n'est jamais notifié de ses propres actions (no-op automatique).

### 15.2 Backend
| Composant | Rôle |
|---|---|
| `app/models/notification.py` | table `notifications` (recipient, actor, type, title, message, link, is_read) |
| `app/services/notification_service.py` | `notify_user()` (destinataire précis), `notify_admins()` (diffusion à tous les ADMIN, no-op si l'acteur est admin), listing paginé, unread-count, mark-read(-all), delete |
| `app/services/notification_ws.py` | registre de connexions WebSocket par `user_id`, envoi ciblé temps réel |
| `app/api/v1/endpoints/notifications.py` | REST (`GET /notifications`, `/unread-count`, `PATCH /{id}/read`, `POST /read-all`, `DELETE /{id}`) + `WS /notifications/ws?token=` |

**Points d'intégration** (déclenchement) :
`recruitment.py` (offre créée, statut candidature changé), `workflow.py`
(entretien planifié, candidature rejetée, négociation lancée),
`interview.py` (entretien confirmé → notifie le RH créateur, entretien
annulé), `employees.py`, `budget.py`, `career.py`, `negotiations.py`,
`reports.py` (action RH → notifie les admins).

### 15.3 Frontend
- Service partagé `core/services/notification.service.ts` : REST + WebSocket
  (`rxjs/webSocket`, reconnexion auto après 5s si déconnecté et toujours
  authentifié).
- **Frontoffice** (candidat) : le mock de notifications déjà présent dans
  `features/frontoffice/header` est remplacé par les vraies données (badge
  de compteur, dropdown avec liste réelle, « tout marquer comme lu »,
  navigation au clic via `link`).
- **Backoffice** (RH/Admin) : nouveau dropdown de notifications dans le
  topbar (`features/backoffice/layout`), même comportement, tokens du
  design system backoffice (`--c-*`).
- Connexion WebSocket établie à l'authentification, fermée au logout.

### 15.4 Tests
`tests/test_notifications.py` (11 tests) : service (create, `notify_admins`
diffuse à tous les admins et exclut l'acteur admin lui-même, mark-read,
mark-all-read, delete), API (401 sans auth, CRUD bout-en-bout, scoping par
destinataire — 404 si on tente de lire la notification d'un autre user),
triggers métier (offre créée par RH → notifie l'admin ; offre créée par un
admin → aucune auto-notification ; changement de statut de candidature →
notifie le candidat ET les admins).

---

## 16. Matching sémantique — Embeddings + pgvector (V1.6)

### 16.1 Principe
Chaque **offre** et chaque **CV analysé** est encodé en vecteur de 384
dimensions (embedding). Deux textes proches par le **sens** ont des vecteurs
proches (similarité cosinus), même sans mots communs — un profil Vue.js
matche une offre React, ce que le scoring par mots-clés exacts ratait.

### 16.2 Architecture
| Composant | Rôle |
|---|---|
| `app/services/embedding_service.py` | encodage : backend **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`, multilingue FR, CPU, chargé paresseusement) OU fallback **hash-v1** (hashing trick déterministe hors-ligne). `EMBEDDINGS_BACKEND=auto\|model\|hash` |
| `app/models/embedding.py` | table `embeddings` : vecteur en **JSON** (portable SQLite/PG) + identifiant du backend producteur (deux vecteurs ne sont comparés que s'ils viennent du même modèle) |
| `app/services/semantic_service.py` | indexation (upsert), matching offre→CVs, candidats similaires. Recherche via **pgvector** (`ORDER BY vec <=> …`, index HNSW) si l'extension est active, sinon **cosinus en Python** — même résultat, moins scalable |
| micro-migration (main.py) | au boot : `CREATE EXTENSION vector` + colonne `vec vector(384)` + index HNSW, best-effort ; sinon fallback Python loggé |

**Indexation automatique** : à l'analyse d'un CV (`scoring_agent`) et à la
création/mise à jour d'une offre. Rattrapage : `POST /semantic/reindex`.

### 16.3 API — `/semantic` (RH/Admin)
`GET /status` (backend effectif, pgvector, volumes indexés) ·
`POST /reindex` · `GET /jobs/{id}/match?limit=` ·
`GET /applications/{id}/similar?limit=`

### 16.4 Frontend (`/admin/recruitment`)
Nouvelle section **« Matching sémantique »** sous le classement IA :
- badge indiquant le backend (« modèle neuronal » violet / « mode lexical
  (fallback) ») et si pgvector est actif ;
- bouton **« 🧠 Matching sémantique »** → liste classée avec **barre de
  similarité** (0-100 %), compétences, et le score mots-clés existant en
  regard (comparaison des deux approches) ;
- bouton **« 👥 Similaires »** par candidat → panneau des profils les plus
  proches dans **toute la CVthèque**, toutes offres confondues (sourcing).
Service : `core/services/semantic.service.ts`.

### 16.5 Activation du modèle neuronal & pgvector
- `pip install sentence-transformers` (fait) — le modèle (~470 Mo) se
  télécharge au premier appel puis est mis en cache HuggingFace local.
- pgvector : `docker-compose.yml` passe à l'image **`pgvector/pgvector:pg16`**.
  Si le volume existant (initialisé par postgres:16-alpine) pose problème :
  `docker compose down -v && docker compose up -d` (base de dev re-seedée au
  boot). Sans pgvector, tout fonctionne en fallback Python.
- Tests : backend **hash** forcé dans `conftest.py` (déterministe, aucun
  téléchargement pendant pytest).

### 16.6 Tests
`tests/test_semantic.py` (8 tests) : vecteur normalisé/déterministe,
discrimination thématique, vecteur nul sur texte vide, upsert sans doublon,
**le bon profil sort premier** (frontend React > frontend Vue > comptable sur
une offre React), exclusion de soi-même dans « similaires », API bout-en-bout
(status, match, similar, reindex, 404, RBAC 401).

---

## 17. Assistant CAG — extractif, sans LLM (V1.7)

### 17.1 Principe (Cache-Augmented Generation, sans Claude)
Le « G » (génération) est **extractif** : le moteur ne génère aucun texte, il
**extrait le passage source le plus pertinent** et le restitue avec sa citation
→ **zéro hallucination possible**. Aucune dépendance à un LLM externe.

- **Cache d'embeddings** : le corpus (base de connaissances + passages de CV)
  est embeddé **une seule fois** (colonne `vector_json` + cache mémoire). À la
  question, seule la question est embeddée puis comparée par cosinus (corpus
  petit → instantané, fonctionne sur SQLite).
- **Cache de réponses** : question → réponse en LRU mémoire (questions
  répétées instantanées, `from_cache=true`).
- Moteur d'embedding = `embedding_service` (sentence-transformers si dispo,
  sinon hash déterministe) — le même que le matching sémantique.

### 17.2 Backend
| Composant | Rôle |
|---|---|
| `app/models/knowledge.py` | `knowledge_entries` (FAQ RH, vecteur caché) + `cv_chunks` (passages de CV cachés) |
| `app/services/cag_service.py` | seed FAQ, indexation (cache), `ask()` (KB extractif + sources), `ask_cv()` (passage exact du CV), CRUD, cache de réponses LRU |
| `app/api/v1/endpoints/cag.py` | `GET /cag/status`, `POST /cag/reindex`, `POST /cag/seed`, `POST /cag/ask` (auth), `POST /cag/cv/{app_id}/ask` (RH), `GET/POST/DELETE /cag/knowledge` (RH) |

Seed automatique de la FAQ + indexation au démarrage (`main.py`).

### 17.3 Frontend
Page **`/admin/assistant`** (sidebar « Assistant ») :
- **Chat** : question → réponse extraite + **badge de confiance** + **puces de
  sources citées** + tag « ⚡ depuis le cache » ; suggestions de départ.
- **Base de connaissances** : ajout/suppression d'entrées (embeddées et
  cachées automatiquement), catégorie, indicateur « indexé ».
- Bandeau de statut : backend d'embedding, nombre d'entrées, taille du cache.
- Service : `core/services/cag.service.ts`.

> Le Q&A sur CV (`/cag/cv/{app_id}/ask`) renvoie le **passage exact** du CV le
> plus pertinent — exposé côté API, branchable sur la fiche candidat.

### 17.4 Tests
`tests/test_cag.py` (8 tests) : découpage en passages, seed/index idempotents,
**réponse ancrée** (l'answer est exactement le contenu d'une entrée existante,
pas une génération), sources renvoyées, **cache-hit** au 2e appel, **Q&A CV**
(la réponse est un sous-texte exact du CV + chunks mis en cache une seule fois),
API + RBAC (401/404/409).

---

## 18. Gestion de contrat + signature électronique (V1.8)

### 18.1 Le maillon manquant : recrutement → RH
Ferme la boucle du pipeline. Après une candidature **ACCEPTED**, un contrat est
généré, signé électroniquement par le candidat, et à la signature un **employé
est créé automatiquement** (la candidature passe `HIRED`, le module
Employés/Budget/Carrière devient la destination naturelle du recrutement).

### 18.2 Cycle de vie
```
ACCEPTED ─► DRAFT ─► SENT ─► SIGNED ─► ACTIVE   (+ DECLINED / EXPIRED)
           (RH       (lien    (candidat  (employé créé,
            complète) public)  signe)     candidature HIRED)
```

### 18.3 Signature électronique — professionnelle & gratuite (sans API payante)
Signature **auto-hébergée** :
- Lien public à token (comme la confirmation d'entretien), **sans compte**.
- **Signature manuscrite** dessinée sur un canvas HTML5 → PNG embarqué dans le PDF.
- **Piste d'audit** : nom du signataire, date UTC, IP, user-agent, **empreinte
  SHA-256 des termes** (scelle le contenu), **identifiant de certificat**.
- **Certificat de signature électronique** (page dédiée du PDF, façon preuve de
  complétion) — le rendu « pro » type DocuSign, à coût nul.
- Consentement explicite obligatoire (case à cocher).

### 18.4 Backend
| Composant | Rôle |
|---|---|
| `app/models/contract.py` | `contracts` (termes, statut, token, audit signature, `employee_id`) |
| `app/services/contract_service.py` | cycle de vie complet, préremplissage salaire (négociation → offre), `sign()` + **activation** (création employé, `HIRED`), `decline()`, empreinte des termes |
| `app/services/contract_pdf.py` | PDF du contrat (parties, articles) + **certificat de signature** (reportlab, hors-ligne) |
| `app/api/v1/endpoints/contracts.py` | RH : from-application, PATCH, send, PDF, list, stats, delete. Public : `GET/POST /contracts/sign/{token}`, `POST /contracts/decline/{token}` |

Notifications à chaque étape (candidat + RH créateur).

### 18.5 Frontend
- **`/admin/contracts`** (sidebar « Contrats ») : KPIs, liste avec statuts,
  **édition inline** du brouillon, **envoi** (génère le lien), **copier le
  lien**, **téléchargement PDF**.
- Bouton **« Contrat »** sur la page Candidatures pour un candidat accepté →
  crée le brouillon.
- **`/contract/sign/:token`** (page publique, sans login) : récap des termes,
  **canvas de signature manuscrite**, consentement, signature ou refus, écran
  de confirmation avec l'identifiant de certificat. Design « Aurora Emerald ».
- Service : `core/services/contract.service.ts`.

### 18.6 Tests
`tests/test_contracts.py` (4 tests) : **cycle de vie complet**
(DRAFT→SENT→SIGNED→ACTIVE), préremplissage salaire, doublon 409, édition,
PDF (brouillon + signé), vue publique, **signature → employé créé +
candidature HIRED + empreinte SHA-256 + certificat**, re-signature 409,
consentement requis (400), refus (410 après), stats + RBAC (401), identité
salarié (CIN) conservée.

### 18.7 Contrat de travail tunisien complet (V1.8.1)
Le PDF (`app/services/contract_pdf.py`) rend un **vrai contrat de droit
tunisien** : soussignés (employeur = société + gérant / employé + date de
naissance + CIN + adresse), **17 articles** (principes, déclarations, fonctions,
durée + période d'essai, obligations, rémunération, horaire 40 h + jours
fériés tunisiens, congés 22 j, biens, résiliation, fidélité, non-concurrence,
litige → tribunaux de Tunis…), mention **« Lu et approuvé »**, blocs de
signature, puis le **certificat de signature électronique**.

- En-tête société **configurable** (`config.py`) : `COMPANY_NAME` (« PIQBIT
  Lab »), `COMPANY_MANAGER` (« Mohamed Derbali »), `COMPANY_TAX_ID`,
  `COMPANY_ADDRESS`, `COMPANY_CITY`.
- Nouveaux champs identité sur le contrat (`employee_birth_date`,
  `employee_cin`, `employee_cin_issue_date`, `employee_address`) — remplis par
  le RH dans le formulaire d'édition du brouillon (`/admin/contracts`),
  scellés dans l'empreinte SHA-256. Micro-migration `ALTER TABLE contracts`
  au boot.
