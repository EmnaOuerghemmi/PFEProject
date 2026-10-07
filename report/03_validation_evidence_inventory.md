# PIQBIT — Inventaire des preuves de validation

Statut : **gabarit `validation_evidence_inventory.md` complété** pour PIQBIT.
Révision : `c8e1bb7` + arbre de travail modifié. Date : **2026-09-22**.

Rappel de la règle : un mécanisme inspectable dans le code, un workflow CI ou un
manifeste prouve qu'un dispositif **existe**, jamais qu'il **passe**. Seule une
exécution datée le prouve. Campagne de référence :
`validation_runs/2026-09-22_validation_summary.md`.

---

## Build et intégration continue

| Domaine | Source de preuve | Objet | État et résultat |
| --- | --- | --- | --- |
| Build frontend de production | `npm run build -- --configuration production` ; `.github/workflows/ci.yml`, tâche `frontend` | Compiler la SPA, vérifier le typage TypeScript strict | **Captured pass** (2026-09-22, local) : code `0`, 36,0 s, bundle initial 1,25 Mo / 246,82 ko transférés, **4 avertissements de budget** |
| Tests unitaires frontend | `npm test -- --watch=false --browsers=ChromeHeadless` ; 39 fichiers `.spec.ts` | Valider composants, services et gardes Angular | **Planned** : non exécutés dans la campagne du 2026-09-22 |
| Tests backend | `pytest -q --no-header` ; `.github/workflows/ci.yml`, tâche `backend` | Valider API, services et règles métier | **Captured failure** (2026-09-22, local, SQLite) : 594 réussis, 3 échoués, 6 ignorés, 607,4 s, code `1` |
| Contrôle de dérive du schéma | `.github/workflows/ci.yml`, étape « Vérifier que les migrations décrivent bien les modèles » | Garantir qu'aucun modèle ne change sans migration Alembic | **Implementation confirmed; execution not captured** |
| Build de l'image backend | `backend/Dockerfile` (multi-étapes, `python:3.14-slim`) | Produire une image d'exécution sans chaîne de compilation | **Implementation confirmed; execution not captured** |
| Build de l'image frontend | `frontend/Dockerfile` (`node:22-alpine` → `nginx:1.27-alpine`) | Produire une image statique légère | **Implementation confirmed; execution not captured** |
| Publication d'artefact | — | Pousser les images vers un registre | **Not applicable** : la CI ne publie aucune image |
| Analyse statique | — | Typage Python, lint | **Not applicable** : aucun outil configuré. **Limitation à déclarer** — rien ne vérifie le typage Python, alors que le projet impose du Python typé |

Versions relevées le 2026-09-22 : Python **3.14.5** (local) / **3.14** (CI) ;
Node **22** ; Angular **19.2.x** ; FastAPI **0.136.1** ; SQLAlchemy **2.0.50** ;
PostgreSQL **16** (image `pgvector/pgvector:pg16`) ; Redis **7**.

---

## Déploiement

| Domaine | Source ou procédure | Objet | État et résultat |
| --- | --- | --- | --- |
| Infrastructure de base | `docker-compose.yml` (profil par défaut : `postgres` + `redis`, sondes de santé, volumes nommés) | Fournir les dépendances de données | **Implementation confirmed; execution not captured** |
| Déploiement applicatif | `docker compose --profile app up -d --build` | Démarrer backend et frontend | **Implementation confirmed; execution not captured** |
| Migration au démarrage | `backend/Dockerfile` : `alembic upgrade head && uvicorn …` ; `app/main.py` `_verify_schema_is_current` | Appliquer le schéma, puis refuser de servir un schéma désynchronisé (journal d'erreur explicite) | **Implementation confirmed; execution not captured** |
| Services de données | Image `pgvector/pgvector:pg16`, Redis 7 | Persistance et cache | **Implementation confirmed; execution not captured** |
| Entrée réseau | `frontend/nginx.conf` : origine unique, proxy `/api/`, bloc WebSocket, gzip, en-têtes de sécurité | Servir la SPA et relayer l'API | **Implementation confirmed; execution not captured** |
| Terminaison TLS | — | Chiffrer le transport | **Not applicable en l'état** : `listen 80` uniquement. `TODO:` à traiter avant tout usage réel |
| Services d'observabilité | — | Métriques, journaux centralisés, traces, alertes | **Not applicable** : non implémentés |
| Services de sécurité d'infrastructure | — | Pare-feu applicatif, politique réseau, coffre à secrets | **Not applicable** : non implémentés |
| Promotion entre environnements | — | Recette → production | **Not applicable** : un seul environnement (local) |
| Retour arrière | — | Revenir à la version précédente | **Planned** : aucune procédure documentée |

Formulation imposée au rapport : décrire la cible d'exécution de manière
générique (« pile conteneurisée sur un hôte unique »), puis préciser pour chaque
résultat l'environnement exact. **Ne jamais qualifier de « production » un
environnement de développement.**

---

## Validation fonctionnelle et à l'exécution

| Validation | Couverture | État et résultat |
| --- | --- | --- |
| Authentification et comptes | Inscription, connexion, jetons, verrouillage, OTP, 2FA (`tests/test_auth.py`, `test_auth_security.py`, `test_users.py`) | Couverts par la campagne du 2026-09-22 (aucun échec dans ces fichiers) |
| Autorisation par rôle | Politique Casbin, héritage, refus par défaut (`tests/test_rbac.py`) | Couverts ; **mais** l'échec E-03 montre qu'un endpoint sensible échappe à l'intention de la politique |
| Cycle de vie des candidatures | Candidature, statuts, retrait, suppression (`test_application_status.py`, `test_withdraw_application.py`, `test_recruitment_extra.py`) | Couverts, sans échec |
| Analyse de CV et notation | Extraction d'expérience, notation, score composite, détail du score (`test_experience_extraction.py`, `test_scoring.py`, `test_composite_score.py`, `test_candidate_score_detail.py`) | Couverts, sans échec |
| Rapprochement sémantique | Indexation et recherche (`test_semantic.py`, `test_similar_jobs.py`, `test_job_recommendations.py`) | Couverts, **mais sur le repli Python** : le backend d'embedding est forcé à `hash` et la base est SQLite. **Le chemin pgvector natif n'est pas validé localement.** |
| Assistant CAG | Recherche extractive et citation (`test_cag.py`) | Couverts, sans échec |
| Entretiens et calendrier | Invitations, créneaux, synchronisation (`test_interview_calendar.py`) | **Captured failure E-01** — dépendant de l'environnement (ignoré en CI, exécuté ici) |
| Test technique | Vivier, génération, exécution, notification (`test_assessment_*.py`) | Couverts, sans échec |
| Négociation salariale | Persistance et analyse (`test_negotiation_persistence.py`, `test_negotiation_analysis.py`) | **Captured failure E-02** — test antérieur au durcissement des autorisations |
| Workflow, tableau de bord, carrière | (`test_workflow_dashboard_career.py`) | **Captured failure E-03** — incohérence d'autorisation réelle |
| Modèle et pipeline salaire | (`test_salary_model.py`, `test_salary_features.py`, `test_salary_pipeline.py`) | Couverts, sans échec |
| Contrats et signature | (`test_contracts.py`) | Couverts, sans échec |
| Notifications | (`test_notifications.py`, `test_emails_non_envoyes.py`) | Couverts, sans échec |
| Bout en bout navigateur | — | **Planned** : aucun harnais E2E |
| Panne et reprise | — | **Planned** : aucun test de résilience |

---

## Sécurité, performance et exploitation

| Domaine | Méthode | État et résultat | Limite |
| --- | --- | --- | --- |
| Authentification | Tests fonctionnels | Couverts au 2026-09-22 | Ne vaut pas audit ; aucune revue cryptographique |
| Autorisation | Tests fonctionnels + politique déclarative | Couverts, **avec une incohérence constatée (E-03)** | La couverture par endpoint n'est pas exhaustive : 173 routes, tous les couples ressource/action ne sont pas testés |
| Gestion des secrets | Inspection : `.gitignore`, `SecretStr` pour `HF_TOKEN`, absence de valeurs par défaut pour le mot de passe superadmin | **Implementation confirmed; execution not captured** | Aucun scan de secrets exécuté sur l'historique Git |
| Analyse de dépendances | — | **Planned** | Aucune. `requirements.txt` est figé par `pip freeze`, sans contrôle de vulnérabilités |
| Sécurité dynamique | — | **Planned** | Aucun scan, aucun test d'intrusion |
| Protection des données personnelles | Inspection : `backend/uploads/` et `backend/backups/` exclus du dépôt avec motif écrit | **Implementation confirmed** | Aucune vérification automatisée qu'aucune donnée de CV n'atteint les journaux |
| Performance et capacité | — | **Planned** | NFR « < 2 s » **non vérifiée**. Seule mesure disponible : taille du bundle, qui **dépasse** le budget |
| Résilience et reprise | — | **Planned** | `restart: unless-stopped` et sondes de santé sont **configurés**, jamais éprouvés |
| Sauvegarde et restauration | — | **Planned** | Des empreintes existent sous `backend/backups/` ; aucune restauration éprouvée, aucune procédure écrite |
| Journaux, métriques, traces, alertes | Inspection de `app/main.py` | Journalisation **implémentée** ; métriques, traces et alertes **non implémentées** | Ne pas revendiquer d'observabilité |
| Sondes de santé | `GET /health`, `HEALTHCHECK` des deux images | **Implementation confirmed; execution not captured** | Aucune exécution capturée |

---

## Preuves visuelles retenues

| Domaine | Preuve à inclure | Emplacement | Valeur probante |
| --- | --- | --- | --- |
| Parcours cœur de métier | `TODO:` captures du parcours candidature → analyse → classement | Chapitre 4 | Montre le comportement décrit dans le texte |
| Livraison | `TODO:` capture du résumé d'exécution GitHub Actions | Chapitre 5 | Montre les portes **configurées et exécutées** |
| Sécurité | `TODO:` capture d'un refus `403` de RBAC | Chapitre 5 | Illustre le refus par défaut |
| Exploitation | `TODO:` capture de l'état sain des conteneurs | Chapitre 5 | Illustre les sondes de santé |
| Supervision | — | — | **Not applicable** |

Une capture illustre ; elle ne remplace jamais un résultat de commande daté.

---

## Vocabulaire d'états utilisé

- `Captured pass` — exécuté, daté, résultat conservé et résumé.
- `Captured failure` — exécuté, échec divulgué avec son analyse.
- `Implementation confirmed; execution not captured` — dispositif inspecté,
  aucun résultat d'exécution revendiqué.
- `Planned` — non réalisé.
- `Not applicable` — exclu, avec justification de périmètre.

« Réussite supposée » est proscrit.

---

## Règles de manipulation et de redaction pour PIQBIT

Éléments concrets à ne jamais faire figurer dans le rapport, ses annexes ou ses
captures :

1. `backend/.env` — secrets réels (SMTP, `SECRET_KEY`, clés d'API).
2. `backend/google-calendar-sa.json` — clé de compte de service Google.
3. `backend/uploads/` — 264 CV réels (données personnelles).
4. `backend/backups/` — empreintes de base contenant des données réelles.
5. Bases `test_*.db` produites par les exécutions de test.
6. Le nom du gérant et le matricule fiscal en valeurs par défaut dans
   `backend/app/core/config.py`.
7. L'adresse électronique de l'autrice figurant dans le cahier des charges.
8. Les chemins absolus du poste (`E:\PIQBIT\…`) présents dans les journaux bruts
   de test et de build.
9. Les jetons des URL publiques de confirmation d'entretien, de passage de test
   et de signature de contrat.

Règle de forme : préférer les compteurs, durées et extraits d'assertion aux
journaux complets. Conserver, hors paquet de rapport, la date, la révision, la
description d'environnement et la commande — c'est le minimum reproductible.
