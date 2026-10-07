# Campagne de validation PIQBIT — 2026-09-22

> **Note de méthode.** `AGENTS.md` référence
> `validation_runs/validation_summary_template.md`, **absent du dépôt**. La
> structure ci-dessous a été reconstituée à partir du vocabulaire d'états et des
> rubriques de `validation_evidence_inventory.md` (M-16). À remplacer si le
> gabarit d'origine est retrouvé.

## Identification de la campagne

| Élément | Valeur |
| --- | --- |
| Date d'exécution | **2026-09-22** |
| Révision testée | `c8e1bb7` **+ modifications non committées** (78 modifiés, 5 supprimés, 17 non suivis) |
| Exécutant | Autrice du projet, poste de développement local |
| Environnement | Windows 11 ; Python 3.14.5 (environnement virtuel `backend/venv`) ; Node 22 ; navigateur non sollicité |
| Base de données des tests | SQLite (`aiosqlite`), fichier temporaire hors dépôt — **pas** PostgreSQL |
| Backend d'embedding | `hash` (déterministe, hors ligne), forcé par `backend/tests/conftest.py` |
| Envoi de courriel | Neutralisé par une fixture de session (`_aucun_email_reel`) |
| Portée | Build frontend de production ; suite de tests backend. **Hors portée** : tests unitaires frontend, E2E, construction et démarrage des images Docker, sécurité dynamique, performance, résilience. |

⚠️ **Écart avec la CI.** La CI exécute la suite backend contre
PostgreSQL `pgvector/pgvector:pg16` et Redis 7, sans fichier `.env`. Cette
campagne locale s'exécute sur SQLite, **avec** le `.env` du poste. Les deux
environnements ne sont donc pas équivalents, et l'un des échecs ci-dessous en
découle directement. Les résultats de cette campagne ne valent pas résultats de
CI.

---

## Résultat 1 — Build frontend de production

| Champ | Valeur |
| --- | --- |
| État de preuve | **Captured pass** |
| Commande | `npm run build -- --configuration production` (répertoire `frontend/`) |
| Code de sortie | `0` |
| Durée | 36,012 s |

Tailles mesurées (bundle initial) :

| Fichier | Taille brute | Transfert estimé |
| --- | --- | --- |
| `main` | 829,05 ko | 129,69 ko |
| plus gros fragment partagé | 200,05 ko | 57,14 ko |
| `polyfills` | 34,58 ko | 11,32 ko |
| `styles` | 15,89 ko | 3,36 ko |
| **Total initial** | **1,25 Mo** | **246,82 ko** |

Plus gros fragments différés : tableau de bord back-office 245,96 ko (71,19 ko
transférés), gestionnaire d'entretiens 84,46 ko, test technique 84,12 ko.

**Avertissements (4)** — le build réussit malgré eux :

1. Bundle initial : budget 800,00 ko dépassé de **451,90 ko** (total 1,25 Mo).
2. `interview-manager.component.css` : 21,26 ko (budget 20,00 ko).
3. `jobs-management.overrides.css` : 35,09 ko (budget 20,00 ko).
4. `jobs-management.component.css` : 27,06 ko (budget 20,00 ko).

**Interprétation.** Le succès du build vaut aussi **vérification complète du
typage TypeScript strict** : la configuration de production échoue sur toute
erreur de typage. En revanche, l'exigence non fonctionnelle du cahier des
charges — « taille bundle frontend < 500 Ko (compressé ~106 Ko) » — **n'est pas
satisfaite** : 1,25 Mo brut et 246,82 ko transférés, soit environ 2,3 fois la
valeur compressée annoncée. À porter en limitation (conflit C-06).

**Limite.** La « taille de transfert estimée » est celle annoncée par le
compilateur Angular ; elle n'a pas été confirmée par une mesure réseau réelle
derrière la compression gzip de nginx.

---

## Résultat 2 — Suite de tests backend

| Champ | Valeur |
| --- | --- |
| État de preuve | **Captured failure** |
| Commande | `pytest -q --no-header` (répertoire `backend/`) |
| Code de sortie | `1` |
| Durée | 607,41 s (10 min 07 s) |
| **Résultat** | **594 réussis, 3 échoués, 6 ignorés, 9 avertissements** |

### Échecs constatés

#### E-01 — `test_interview_calendar.py::test_sync_google_reuses_request_session`

- Attendu `200`, obtenu **`502`** :
  `{"detail":"La création de l'événement Google Calendar a échoué (voir logs)."}`
- Le test est gardé par `skipif(not _GOOGLE_CONFIGURED)`. Il **est ignoré en
  CI** (aucun `.env`) et **s'exécute sur ce poste**, où Google Calendar est
  configuré. Le test substitue `google_calendar_client.create_interview_event`,
  mais l'appel réel n'emprunte manifestement pas cette référence substituée.
- **Nature** : défaillance dépendante de l'environnement, portant sur le
  dispositif de test. Elle **ne démontre pas** de défaut du produit, et **ne
  démontre pas non plus** que la synchronisation fonctionne.
- **Suite à donner** : `TODO:` corriger la substitution, ou rendre le test
  indépendant de la configuration du poste.

#### E-02 — `test_negotiation_persistence.py::test_initiate_persists_and_history_returns_it`

- Attendu `200`, obtenu **`403`** :
  `{"detail":"Action non autorisée pour votre rôle (negotiations:read)."}`
- Le test enregistre un compte ordinaire (rôle `CANDIDAT` par défaut) puis
  appelle `POST /api/v1/negotiations/initiate`. Depuis l'introduction du
  contrôle Casbin (commit `c8e1bb7`, 2026-09-15), cette route exige
  `negotiations:read`, qu'un candidat n'a pas.
- **Nature** : test **antérieur** au durcissement des autorisations. Le refus
  observé est conforme à la politique ; c'est l'attente du test qui est périmée.
- **Suite à donner** : `TODO:` réécrire le test avec un acteur RH ou ADMIN.

#### E-03 — `test_workflow_dashboard_career.py::test_negociation_interdite_au_personnel_rh_simple`

- Attendu `403`, obtenu **`200`**.
- Un utilisateur `RECRUTEUR` appelle
  `POST /api/v1/recruitment/applications/{id}/start-negotiation` ; la
  négociation s'exécute jusqu'au bout (journal : décision `ACCEPTED` à 3000).
- **Cause vérifiée dans le code** : l'endpoint est gardé par
  `Depends(require("workflow", "write"))`
  (`backend/app/api/v1/endpoints/workflow.py:341-343`), or
  `backend/app/core/rbac_policy.csv:51` accorde `workflow, write` au rôle
  `RECRUTEUR`. La permission `negotiations, write` n'est en revanche accordée
  qu'à `RH` (et par héritage à `ADMIN`).
- **Nature** : **incohérence réelle entre l'intention de la politique et la
  garde effective de l'endpoint**. Une action qui engage financièrement
  l'entreprise est atteignable par un rôle que la politique entend exclure.
- **Portée de l'affirmation** : ce constat provient d'un test fonctionnel
  exécuté et reproductible ; il n'est le résultat d'aucun audit de sécurité, et
  aucune conclusion générale sur la sécurité du système n'en découle.
- **Suite à donner** : `TODO:` arbitrer — soit aligner la garde de l'endpoint
  sur `negotiations:write`, soit corriger la politique et le test. À traiter
  **avant** la rédaction du chapitre 5, puis à re-tester.

### Tests ignorés

6 tests ignorés, dont des tests conditionnés à la disponibilité d'une
configuration externe. `TODO:` dresser la liste nominative des 6 et justifier
chaque exclusion dans le rapport.

### Avertissements

9 avertissements, tous de la même famille :
`RuntimeWarning: coroutine 'Connection._cancel' was never awaited`, attribués à
l'interaction entre `asyncio` (Python 3.14) et le pilote de base de données dans
le contexte de test. **Sans effet constaté sur les résultats** ; à ne pas
présenter comme un défaut avéré sans analyse complémentaire.

---

## Validations non exécutées dans cette campagne

Aucune des lignes ci-dessous ne doit être présentée comme réussie.

| Validation | État |
| --- | --- |
| Tests unitaires frontend (Karma, 39 fichiers `.spec.ts`) | **Planned** |
| Contrôle de dérive du schéma Alembic | **Implementation confirmed; execution not captured** |
| Construction des images Docker | **Implementation confirmed; execution not captured** |
| Démarrage de la pile complète et sonde `/health` | **Implementation confirmed; execution not captured** |
| Tests de bout en bout | **Planned** — aucun harnais dans le dépôt |
| Analyse statique (typage Python, lint) | **Not applicable** — aucun outil configuré |
| Analyse de dépendances et de secrets | **Planned** |
| Sécurité dynamique | **Planned** |
| Performance et capacité (NFR « < 2 s ») | **Planned** |
| Résilience, bascule, restauration | **Planned** |
| Disponibilité (NFR « 99,5 % ») | **Non vérifiable** — aucun environnement de production |
| Accessibilité (NFR contraste ≥ 4,5:1) | **Planned** |

---

## Reproduction

```bash
# Suite backend (SQLite, hors ligne)
cd backend
python -m pytest -q --no-header

# Build frontend de production
cd frontend
npm ci
npm run build -- --configuration production
```

Variables requises par `Settings` à l'import de `app.main` : `DATABASE_URL` et
`SECRET_KEY`. **Aucune valeur réelle n'est reproduite ici** ; voir
`backend/.env.example`.

---

## Manipulation des preuves

- Les journaux bruts contiennent des chemins de poste de travail
  (`E:\PIQBIT\…`), des identifiants techniques et la configuration locale : ils
  sont **conservés hors du paquet de rapport** et ne sont pas committés.
- Seuls les compteurs, les durées, les assertions et les extraits ci-dessus —
  déjà expurgés — sont destinés au rapport.
- Aucun secret, jeton, adresse réelle ni donnée de CV n'apparaît dans ce
  document.

## Synthèse honnête

Au 2026-09-22, le build frontend de production **réussit** et **594 tests
backend sur 603 exécutés réussissent**, pour **3 échecs** et 6 tests ignorés.
La suite backend est donc **en échec** (code de sortie `1`). Parmi les trois
échecs, un est un artefact d'environnement (E-01), un est un test périmé
(E-02), et **un révèle une incohérence d'autorisation réelle** (E-03). Aucune
propriété de performance, de disponibilité, de résilience ou de sécurité
dynamique n'a été mesurée.
