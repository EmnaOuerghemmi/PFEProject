# PIQBIT — Inventaire de preuves du rapport

Statut : **gabarit `evidence_inventory.md` complété** pour PIQBIT.
Révision de preuve : `c8e1bb7` + arbre de travail modifié. Date : **2026-09-22**.

Règles conservées : toute affirmation d'implémentation s'appuie sur un artefact
inspectable ou un résultat daté ; les preuves confirmées, prévues et
indisponibles restent distinctes ; aucune vérification non exécutée n'est
présentée comme réussie ; secrets, données personnelles, URL privées et chemins
de poste de travail sont exclus.

Tous les chemins ci-dessous sont **relatifs à la racine du dépôt**. Les chemins
absolus du poste (`E:\PIQBIT\…`) ne doivent jamais apparaître dans le rapport
final ni dans une capture.

---

## Preuves d'architecture

| Usage dans le rapport | Source de preuve | Constat confirmé | Statut |
| --- | --- | --- | --- |
| Contexte système | `frontend/src/app/app.routes.ts`, `backend/app/api/v1/router.py`, `backend/app/core/config.py` | Frontière : SPA navigateur + API. Acteurs : visiteur, candidat, recruteur, RH, admin. Dépendances externes **toutes optionnelles** : SMTP, Google Calendar/Meet, Jitsi, Anthropic, Gemini, Hugging Face ; chacune a un repli documenté. | Confirmé |
| Frontière client | `frontend/package.json`, `frontend/src/app/app.routes.ts`, `frontend/src/app/core/` | Angular 19.2.x, composants autonomes, chargement différé des modules lourds, gardes `authGuard` / `adminGuard` / `permissionGuard`, intercepteur JWT. | Confirmé |
| Frontière service | `backend/app/api/v1/endpoints/` (18 modules), `backend/app/services/` (34 services), `backend/app/agents/` (9 agents) | API REST `/api/v1` + 2 points WebSocket ; 173 décorateurs de route ; séparation endpoint → service → modèle ; schémas Pydantic en frontière. | Confirmé |
| Persistance | `backend/app/models/` (25 tables), `backend/alembic/versions/` (18 révisions) | PostgreSQL autoritaire ; Redis pour cache et limitation de débit ; système de fichiers pour les CV (`backend/uploads/`, volume Docker `uploads`). | Confirmé |
| Recherche vectorielle | `backend/app/services/semantic_service.py`, migration `9b1c4d2e7f30_pgvector_native_search.py` | Colonne `vec vector(384)` + index HNSW quand l'extension `vector` est présente ; sinon similarité calculée en Python sur vecteurs JSON. | Confirmé |
| Authentification et autorisation | `backend/app/core/security.py`, `dependencies.py`, `rbac.py`, `rbac_model.conf`, `rbac_policy.csv` | JWT HS256 accès + rafraîchissement, bcrypt 12 tours, TOTP + codes de secours, OTP d'adresse ; autorisation Casbin déclarative, refus par défaut, héritage `RECRUTEUR → RH → ADMIN`. | Confirmé |
| Exécution et orchestration | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | Deux images multi-étapes ; profil Compose `app` pour la pile complète, infrastructure seule par défaut ; utilisateur non privilégié côté backend ; sondes `HEALTHCHECK`. | Confirmé |
| Déploiement | `docker-compose.yml`, `frontend/nginx.conf` | Origine unique via nginx (port hôte 8080), proxy `/api/`, bloc WebSocket dédié. **Aucun environnement cible, aucun TLS.** | Confirmé, avec lacune déclarée |
| Observabilité | `backend/app/main.py`, Dockerfiles, `backend/app/models/user.py` | Journalisation standard configurée au démarrage ; `GET /health` ; sondes conteneur ; table `audit_logs`. **Aucune métrique, trace, alerte ni tableau de bord d'exploitation.** | Confirmé (portée limitée) |
| Contrôles de sécurité | `backend/app/core/config.py`, `security.py`, `frontend/nginx.conf`, `backend/.gitignore` | Limitation de débit par route, verrouillage de compte, égalisation de latence, CORS piloté par configuration, en-têtes nginx, liste blanche de dépôt de fichiers, exclusion des CV et des secrets du dépôt. | Confirmé |
| Chaîne de livraison | `.github/workflows/ci.yml` | 2 tâches parallèles ; contrôle de dérive Alembic ; `pytest` ; build Angular de production ; tests Karma. **Aucune publication d'artefact, aucun déploiement, aucun retour arrière.** | Confirmé (portée limitée) |

---

## Preuves de diagrammes

**Neuf diagrammes produits le 2026-09-22.** L'outil retenu est **TikZ**, décidé
sur deux critères posés plus bas dans cette section : source éditable et
versionnée, rendu vectoriel. Les sources vivent dans `report/diagrams/*.tex`
et sont composées directement — il n'y a donc pas d'actif rendu intermédiaire
à maintenir en parallèle, ni de risque de désynchronisation entre une source
et son export.

Chaque diagramme est inséré par `\pqfigure{...}` (ou `\pqfigurewide` en
paysage), défini dans `config/commands.tex`.

| Diagramme | Source | Insertion | Emplacement | Statut |
| --- | --- | --- | --- | --- |
| Cas d'utilisation | `report/diagrams/use_cases.tex` | `fig:use_cases` | Chapitre 2, §2.5 | **produit** — 14 cas, héritage de rôles conforme à `rbac_policy.csv` |
| Contexte système | `report/diagrams/system_context.tex` | `fig:system_context` | Chapitre 3, §3.1 | **produit** — les 6 dépendances externes et leur repli |
| Vue logique / composants | `report/diagrams/component_view.tex` | `fig:component_view` | Chapitre 3, §3.2 | **produit** — 18 modules d'endpoints, 33 services, 25 tables |
| Modèle de données | `report/diagrams/domain_model.tex` | `fig:domain_model` | Chapitre 3, §3.4 | **produit** — 25 tables en 6 bandes, paysage ; signale les 2 liens non contraints |
| Séquence : candidature → analyse → notation → classement | `report/diagrams/sequence_scoring.tex` | `fig:sequence_scoring` | Chapitre 3, §3.6 | **produit** — montre la réponse `201` émise avant l'analyse |
| Séquence : contrat → signature par jeton → activation employé | `report/diagrams/sequence_contract_signature.tex` | `fig:sequence_contract` | Chapitre 3, §3.6 | **produit** — gardes d'état et idempotence de la création d'employé |
| Vue de sécurité et frontières de confiance | `report/diagrams/security_view.tex` | `fig:security_view` | Chapitre 3, §3.7 | **produit** — fait apparaître les 9 routes publiques à jeton et le constat E-03 |
| Vue de déploiement | `report/diagrams/deployment_view.tex` | `fig:deployment_view` | Chapitre 3, §3.8 | **produit** — déclare l'absence de TLS et d'environnement cible |
| Flux de livraison et de validation | `report/diagrams/delivery_flow.tex` | `fig:delivery_flow` | Chapitre 5, §5.4 | **produit** — déclare le point d'arrêt de la chaîne |
| Planning | `generate_gantt.py` | `fig:gantt_previsionnel` | Chapitre 1, §1.7 | **inséré** — légendé **« prévisionnel »**, avec mention explicite qu'il ne prouve aucun déroulement |

**Pourquoi TikZ plutôt qu'un outil de diagramme externe.** Un export d'outil
graphique est un binaire : il se relit mal en revue, se compare mal entre deux
versions, et se désynchronise de sa source dès que l'un des deux est modifié
seul. Une source TikZ est du texte versionné, composée à chaque build — la
figure du PDF ne peut pas diverger de sa source. Le coût est réel : la mise en
page se règle à la main.

**Convention graphique.** Les styles partagés sont dans
`config/tikz_styles.tex` : un seul vocabulaire pour les neuf vues. Le trait
plein marque une dépendance indispensable, le trait discontinu une dépendance
facultative, l'ocre une frontière ou un constat à déclarer. Aucune couleur
n'est décorative.

---

## Preuves de captures d'écran

**Aucune capture n'existe dans le dépôt à ce jour.** Toutes doivent être
produites sur un jeu de démonstration (`backend/scripts/seed_demo.py` —
comptes `@piqbit.demo`, mot de passe `Demo1234!`), jamais sur les données
réelles de `backend/uploads/` (264 CV).

> **Mode opératoire détaillé : `report/06_screenshot_plan.md`.** Pour chacune
> des 28 captures, ce document donne le chemin exact dans l'application, ce qui
> doit être visible, et ce qui doit être masqué. La liste à cocher est
> dupliquée dans `report/assets/screenshots/README.md`, là où les fichiers
> sont attendus.

| Groupe | Usage | Nombre | Statut |
| --- | --- | --- | --- |
| Parcours candidat | Chapitre 4 | 6 | planned — spécifiées (C-1 à C-6) |
| Parcours recruteur / RH | Chapitre 4 | 10 | planned — spécifiées (R-1 à R-10) |
| RH interne et pilotage | Chapitre 4 | 6 | planned — spécifiées (H-1 à H-6) |
| Administration | Chapitre 4 | 3 | planned — spécifiées (A-1 à A-3) |
| Sécurité | Chapitre 5 | 3 | planned — spécifiées (S-1 à S-3) ; masquer tout secret TOTP réel |
| Livraison et exécution | Chapitre 5 | 5 | planned — spécifiées (L-1 à L-5) |
| Supervision | — | — | **Not applicable** : aucune télémétrie implémentée |

Les 16 noms de fichiers publiés dans la révision précédente de ce document sont
**conservés à l'identique** ; les 12 autres couvrent des sections du chapitre 4
qui n'avaient aucune preuve visuelle.

Contrôle de redaction obligatoire avant inclusion : noms et adresses réels,
barre d'URL, historique du navigateur, notifications système, chemins
`E:\PIQBIT\…`, jetons dans les URL publiques de confirmation, de test et de
signature.

**Deux captures seront des constats d'échec** si elles sont prises en l'état :
`ci_test_failure_detail.png` (trois tests échoués) et
`bundle_budget_warning.png` (budget de bundle dépassé). Elles figurent au
rapport avec leur analyse — les omettre contredirait le chapitre 5.

---

## État des preuves de validation

Résultats détaillés : `validation_runs/2026-09-22_validation_summary.md`.

| Preuve | Commande ou source | État de preuve | Usage |
| --- | --- | --- | --- |
| Build frontend de production | `npm run build -- --configuration production` (dans `frontend/`) | **Captured pass** — 2026-09-22 | Qualité de build ; typage TypeScript strict ; mesure de taille de bundle |
| Suite de tests backend | `pytest -q --no-header` (dans `backend/`) | **Captured failure** — 2026-09-22 : 594 réussis, **3 échoués**, 6 ignorés, code de sortie `1` | Correction fonctionnelle ; l'échec E-03 est une incohérence d'autorisation réelle |
| Contrôle de dérive du schéma | `.github/workflows/ci.yml`, étape « Vérifier que les migrations décrivent bien les modèles » | **Implementation confirmed; execution not captured** | Intégrité du schéma |
| Tests unitaires frontend | `npm test -- --watch=false --browsers=ChromeHeadless` ; 39 fichiers `.spec.ts` | **Planned** | Correction des composants |
| Analyse statique | — | **Not applicable** — aucun outil configuré | À déclarer en limitation : le typage Python n'est vérifié par rien |
| Tests d'intégration | Inclus dans `pytest` via client ASGI `httpx` sur SQLite | Couverts par la campagne, **portée réduite** | Intégration API ↔ service ↔ base ; **le chemin pgvector natif n'est pas couvert** |
| Tests de bout en bout | — | **Planned** | Parcours utilisateur complet |
| Construction des images Docker | `docker compose --profile app build` | **Implementation confirmed; execution not captured** | Opérabilité |
| Démarrage de la pile | `docker compose --profile app up -d` puis `GET /health` | **Implementation confirmed; execution not captured** | Préparation au déploiement |
| Validation de sécurité | `backend/tests/test_auth_security.py`, `test_rbac.py` | Couverts par la campagne (tests fonctionnels) | Authentification, verrouillage, RBAC |
| Sécurité dynamique, dépendances, secrets | — | **Planned** | Assurance sécurité — **aucune à ce jour** |
| Performance et capacité | — | **Planned** | NFR « < 2 s » du cahier des charges : **non vérifiée** |
| Résilience et restauration | — | **Planned** | Aucun test de panne ni de restauration |
| Validation d'observabilité | — | **Not applicable** — rien à valider | Visibilité opérationnelle |
| Métriques du modèle de salaire | Artefact `backend/salary_model_piqbit.p` (clé `metrics`), daté 2026-09-10 | **Captured pass** — métriques **embarquées dans l'artefact**, relues le 2026-09-22 | Chapitre 4 (justification du choix de modèle) |
| Audit du jeu de données salarial | `backend/datasets/audit_report.json`, daté 2026-09-10 | **Captured pass** | Chapitre 4 (qualité des données) |

---

## Traçabilité exigences → implémentation → validation

Identifiants repris du cahier des charges v1.0 (06 mai 2026). Les capacités
implémentées **absentes** du cahier des charges reçoivent un identifiant
provisoire `EXT-nn`, à faire approuver (`TODO: M-09`, C-01).

### Exigences du cahier des charges

| Exigence | Implémentation | Validation | Lacune |
| --- | --- | --- | --- |
| AUTH-01 Inscription | `endpoints/auth.py` `POST /register` ; limitation 10/h | `tests/test_auth.py` | — |
| AUTH-02 Vérification d'adresse | `POST /verify-email`, `/resend-verification` ; OTP 6 chiffres, 15 min, 5 tentatives par compte | `tests/test_auth.py`, `test_auth_security.py` | Envoi SMTP réel non validé de bout en bout |
| AUTH-03 Connexion | `POST /login`, `/token` ; verrouillage 5/15 min ; égalisation de latence | `tests/test_auth.py`, `test_auth_security.py` | — |
| AUTH-04 Déconnexion | `POST /logout` ; `tokens_valid_from` | `tests/test_auth.py` | — |
| AUTH-05 / AUTH-06 Mot de passe oublié et réinitialisation | `POST /forgot-password`, `/reset-password` ; limitation 3/10 min | `tests/test_auth.py` | — |
| AUTH-07 Rafraîchissement de jeton | `POST /refresh` ; limitation 60/10 min | `tests/test_auth.py` | — |
| AUTH-08 Contrôle d'accès (RBAC) | Casbin : `core/rbac.py`, `rbac_policy.csv`, `rbac_model.conf` ; `permissionGuard` côté client | `tests/test_rbac.py` | Le cahier des charges décrit 3 rôles, l'implémentation en a 4 (C-02) |
| OFF-01 … OFF-08 Offres | `endpoints/recruitment.py` : liste, détail, création, `PATCH`, `PUT`, suppression, activation, compteur | `tests/test_recruitment_extra.py` | `TODO:` vérifier la couverture de chaque identifiant un à un |
| CAND-01 Postuler avec CV | `POST /apply/{job_id}` ; `services/cv_storage.py` (PDF/DOC/DOCX, 5 Mo) | `tests/test_candidate_cv_and_expectation.py` | — |
| CAND-02 / CAND-03 Mes candidatures et compteurs | `GET /my-applications` | `tests/test_recruitment_extra.py` | `TODO:` confirmer les compteurs |
| CAND-04 / CAND-05 Aperçu et téléchargement du CV | `GET /cv-preview/{path}`, `/cv-download/{path}` | `TODO:` identifier le test couvrant l'isolation d'accès | Contrôle d'appartenance à vérifier explicitement |
| CAND-06 Liste des candidats | `GET /jobs/{id}/applications` | `tests/test_recruitment_extra.py` | — |
| CAND-07 Changement de statut | `PATCH /applications/{id}` ; `models/application_status.py` | `tests/test_application_status.py` | — |
| CAND-08 Suppression et nettoyage du CV | `DELETE /applications/{id}` | `tests/test_recruitment_extra.py` | — |
| NFR Performance « < 2 s » | — | **Non vérifiée** | Aucune mesure |
| NFR Bundle « < 500 Ko » | — | **Captured failure** : 1,25 Mo brut / 246,82 ko transférés (2026-09-22) | Exigence non satisfaite (C-06) |
| NFR Disponibilité « 99,5 % » | — | **Non vérifiée** | Aucun environnement de production (C-07) |
| NFR Sécurité — bcrypt, JWT, validation de fichiers | `core/security.py`, `services/cv_storage.py` | `tests/test_auth_security.py` | — |
| NFR Accessibilité — contraste ≥ 4,5:1 | `frontend/src/styles/` | **Non vérifiée** | Aucun audit d'accessibilité |
| NFR Compatibilité navigateurs, responsive | `frontend/src/…` | **Non vérifiée** | Aucun test multi-navigateurs |

### Capacités implémentées hors cahier des charges

| Identifiant provisoire | Capacité | Implémentation | Validation |
| --- | --- | --- | --- |
| EXT-01 | Analyse de CV et extraction de compétences | `services/cv_parser.py`, `nlp_service.py` | `tests/test_experience_extraction.py` |
| EXT-02 | Notation pondérée et classement | `services/scoring_service.py`, `composite_score_service.py` | `tests/test_scoring.py`, `test_composite_score.py`, `test_candidate_score_detail.py` |
| EXT-03 | Rapprochement sémantique | `services/semantic_service.py`, `embedding_service.py` | `tests/test_semantic.py`, `test_similar_jobs.py` |
| EXT-04 | Recommandation d'offres au candidat | `services/recommendation_service.py` | `tests/test_job_recommendations.py` |
| EXT-05 | Assistant CAG extractif | `services/cag_service.py` | `tests/test_cag.py` |
| EXT-06 | Entretiens, calendrier, visioconférence | `services/interview_service.py` | `tests/test_interview_calendar.py` |
| EXT-07 | Test technique | `services/assessment_service.py` | `tests/test_assessment_*.py` (4 fichiers) |
| EXT-08 | Prédiction salariale et négociation | `services/salary_prediction_service.py`, `negotiation_analysis_service.py` | `tests/test_salary_model.py`, `test_salary_features.py`, `test_salary_pipeline.py`, `test_negotiation_analysis.py`, `test_negotiation_persistence.py` |
| EXT-09 | Contrats et signature électronique | `services/contract_service.py`, `contract_pdf.py` | `tests/test_contracts.py` |
| EXT-10 | Employés, budget, carrière | `endpoints/employees.py`, `budget.py`, `career.py` | `tests/test_budget_employees.py`, `test_employee_profile.py`, `test_workflow_dashboard_career.py` |
| EXT-11 | Rapports et décision | `services/report_service.py`, `decision_service.py` | `tests/test_reports_module.py`, `test_decision_logic.py` |
| EXT-12 | Notifications et WebSocket | `services/notification_service.py`, `notification_ws.py` | `tests/test_notifications.py` |
| EXT-13 | Retrait de candidature | `POST /my-applications/{id}/withdraw` | `tests/test_withdraw_application.py` |

`TODO:` transformer `EXT-01` … `EXT-13` en identifiants d'exigence approuvés
(`FR-<DOMAINE>-<NUMÉRO>`) une fois le périmètre confirmé, et compléter les
critères d'acceptation.

---

## Notes de rédaction

**Architecture** — décrire les responsabilités avant les technologies. Le point
distinctif de PIQBIT est la **dégradation gracieuse systématique** : embeddings
neuronaux → hachage déterministe ; pgvector natif → calcul Python ; Google Meet
→ Jitsi ; modèle ML → heuristique ; LLM → absence de fonctionnalité plutôt
qu'erreur. C'est une décision d'architecture à justifier, pas un détail.

**Implémentation** — rattacher chaque sous-système à ses modules, exigences et
tests. Distinguer ce qui est exécuté de ce qui est seulement configuré. Ne pas
présenter les agents de `backend/app/agents/` comme un système multi-agents
autonome sans en vérifier l'usage réel depuis les endpoints.

**Validation** — séparer build, fonctionnel, intégration, sécurité,
performance, résilience, déploiement. Reporter dates, environnement, commande,
résumé de résultat et limites. **Les échecs constatés le 2026-09-22 doivent
figurer dans le rapport**, avec leur analyse ; les masquer contredirait la règle
d'intégrité de `pfe_report_spec_refined.md`.
