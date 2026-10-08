# PIQBIT — Plan de rapport

Date : **2026-09-22**. Fondé sur `pfe_report_spec_refined.md` §7 et sur les
faits confirmés de `01_project_report_spec.md`.

> **Révision du 2026-09-22 (soir).** Les **neuf diagrammes** annoncés « à
> produire » dans ce plan existent désormais (sources TikZ dans
> `report/diagrams/`, insérées et compilées — cf. `02_evidence_inventory.md`).
> Les **28 captures d'écran** sont spécifiées une par une dans
> `06_screenshot_plan.md` ; elles restent à prendre. Les états « Diagrammes à
> produire » ci-dessous sont donc caducs et corrigés dans les tableaux.

**Règle de lecture.** Chaque section indique ses preuves. Une section dont les
preuves sont `TODO:` **ne doit pas être rédigée** avant que la preuve existe :
la rédiger reviendrait à inventer.

Structure : introduction générale, 5 chapitres, conclusion générale, annexes.
Le chapitre 4 est organisé **par sous-système**, pas par sprint — l'historique
Git ne documente pas un déroulement itératif (M-11).

---

## Introduction générale

Cadre, problématique, objectifs, approche, contribution, organisation du
document. **Aucun résultat qui ne soit démontré plus loin.**
Preuves : `TODO: M-09`. Volume indicatif : 2 pages.

---

## Chapitre 1 — Cadre général du projet

| § | Contenu | Preuves | État |
| --- | --- | --- | --- |
| 1.1 | Organisme d'accueil, dans les limites de divulgation | `TODO: M-05, M-14` | **Bloqué** |
| 1.2 | Existant et limites constatées | `TODO: M-09` | **Bloqué** |
| 1.3 | Problématique | `TODO: M-09` | **Bloqué** |
| 1.4 | Solution proposée et valeur attendue | Cahier des charges §1.1–1.2 + périmètre implémenté | Partiel |
| 1.5 | Objectifs et livrables | Cahier des charges §1.2, §12 | Prêt |
| 1.6 | Périmètre et exclusions | Cahier des charges §1.3, §10 ; exclusions constatées (observabilité, hébergement, tests non fonctionnels) | Prêt |
| 1.7 | Méthode, planification, contraintes, risques | `gantt_diagram.png` (**prévisionnel**), cahier des charges §11 | Partiel — `TODO: M-11, M-12` |

Transition : du besoin exprimé aux exigences formalisées.

---

## Chapitre 2 — Analyse et spécification des exigences

| § | Contenu | Preuves | État |
| --- | --- | --- | --- |
| 2.1 | Acteurs et rôles | Cahier des charges §2 (4 acteurs) ; `backend/app/models/user.py` (4 rôles), `core/rbac_policy.csv` | Prêt — **expliciter le conflit C-02** |
| 2.2 | Exigences fonctionnelles du périmètre initial | Cahier des charges §3 : AUTH-01…08, OFF-01…08, CAND-01…08 | Prêt |
| 2.3 | Exigences fonctionnelles du périmètre étendu | `02_evidence_inventory.md`, EXT-01…13 | Partiel — `TODO:` approbation et renumérotation |
| 2.4 | Exigences non fonctionnelles mesurables | Cahier des charges §4 (11 exigences avec critères) | Prêt — **signaler d'emblée celles qui ne sont pas vérifiées** |
| 2.5 | Cas d'utilisation principaux | Figure `fig:use_cases` (14 cas, produite) | **Figure produite** — fiches détaillées à rédiger |
| 2.6 | Critères d'acceptation et priorisation | Cahier des charges §4 ; `TODO:` pour EXT-01…13 | Partiel |
| 2.7 | Matrice de traçabilité exigence → implémentation → test | `02_evidence_inventory.md` | Prêt (à compléter) |

Figures : diagramme de cas d'utilisation (**produit**). Tableaux : exigences
fonctionnelles, exigences non fonctionnelles, traçabilité.

---

## Chapitre 3 — Architecture et conception

| § | Contenu | Preuves | État |
| --- | --- | --- | --- |
| 3.1 | Contexte système et dépendances externes | `app.routes.ts`, `router.py`, `core/config.py` | Prêt — **insister sur le caractère optionnel de toutes les dépendances externes** |
| 3.2 | Vue logique et composants | 18 modules d'endpoints, 34 services, 9 agents, SPA Angular | Prêt |
| 3.3 | Modèle de données et évolution du schéma | 25 tables, 18 révisions Alembic, garde-fou de dérive en CI | Prêt — **décision D-01** |
| 3.4 | Interfaces et contrats | 173 routes sous `/api/v1`, schémas Pydantic, 2 points WebSocket | Prêt |
| 3.5 | Séquences principales | Candidature → analyse → notation → classement ; contrat → signature → activation employé | **Diagrammes produits** (`fig:sequence_scoring`, `fig:sequence_contract`) |
| 3.6 | Sécurité, confiance et vie privée | `core/security.py`, `rbac.py`, politique CSV, en-têtes nginx ; **liens publics à jeton** comme frontière de confiance explicite | Prêt — **décision D-02** |
| 3.7 | Vue de déploiement | `docker-compose.yml`, deux Dockerfiles, `nginx.conf` | Prêt — **déclarer l'absence de TLS et d'environnement cible** |
| 3.8 | Décisions d'architecture | Fiches D-01 à D-08 de `04_report_depth_gap_analysis.md` | À rédiger |

Figures : contexte, composants, modèle de données, deux séquences, sécurité,
déploiement — **les sept sont produites** (`report/diagrams/`).

---

## Chapitre 4 — Implémentation

Organisation par sous-système. Pour chacun : objectif, exigences couvertes,
conception retenue, difficulté significative, preuve.

| § | Sous-système | Preuves | Difficulté à raconter |
| --- | --- | --- | --- |
| 4.1 | Socle : configuration, schéma, journalisation | `core/config.py`, `main.py`, Alembic | Dérive de schéma entre environnements (D-01) |
| 4.2 | Identité, authentification, 2FA | `core/security.py`, `endpoints/auth.py` | Égalisation de latence contre l'énumération de comptes ; plafonnement des tentatives **par compte** et non par IP |
| 4.3 | Autorisation par rôle | `core/rbac*.{py,conf,csv}`, `permissionGuard` | Externalisation de la politique (D-02) ; **et l'écart révélé par E-03** |
| 4.4 | Offres et candidatures | `endpoints/recruitment.py`, `services/cv_storage.py` | Validation de dépôt de fichier, nettoyage à la suppression |
| 4.5 | Analyse de CV et notation | `cv_parser.py`, `nlp_service.py`, `scoring_service.py` | Normalisation des compétences : le repli appliqué globalement faisait perdre les compétences non reconnues et **surnotait** les candidats |
| 4.6 | Rapprochement sémantique | `semantic_service.py`, `embedding_service.py`, migration pgvector | Chemin natif et repli Python (D-03) ; écriture d'embedding hors cycle applicatif invisible à la recherche native |
| 4.7 | Assistant CAG | `cag_service.py` | Extractif plutôt que génératif (D-06) |
| 4.8 | Entretiens et visioconférence | `interview_service.py` | Google Meet puis repli Jitsi dérivé du jeton ; resynchronisation et session de base de données |
| 4.9 | Test technique | `assessment_service.py` | Seuil d'éligibilité **côté serveur**, jamais côté navigateur |
| 4.10 | Prédiction salariale et négociation | `salary_features.py`, `salary_prediction_service.py`, `scripts/salary_ml_pipeline.py` | Audit du jeu de données (net→brut par dichotomie sur le barème social réel) ; sélection sur l'erreur de test (D-04) ; retrait de la variable colinéaire (D-05) ; `java` détecté dans « JavaScript » ; titres français non reconnus |
| 4.11 | Contrats et signature | `contract_service.py`, `contract_pdf.py` | Signature auto-hébergée, empreinte SHA-256 des termes, certificat (D-07) |
| 4.12 | RH interne : employés, budget, carrière | `endpoints/employees.py`, `budget.py`, `career.py` | — |
| 4.13 | Rapports, décision, notifications | `report_service.py`, `decision_service.py`, `notification_ws.py` | Diffusion WebSocket authentifiée par jeton |
| 4.14 | Interface Angular | `frontend/src/app/` | Chargement différé pour contenir le bundle initial — **et son insuffisance constatée le 2026-09-22** |
| 4.15 | Conteneurisation et service statique | Dockerfiles, `nginx.conf` | Variante CPU de torch (~2,5 Go évités) ; utilisateur non privilégié ; sonde IPv4 contre résolution IPv6 (D-08) |

Captures : 28 captures spécifiées une par une dans `06_screenshot_plan.md`
(chemin dans l'application, contenu attendu, masquages obligatoires). Toutes
encore `planned` : aucune n'est prise à ce jour.

---

## Chapitre 5 — Validation, livraison et exploitation

| § | Contenu | Preuves | État |
| --- | --- | --- | --- |
| 5.1 | Stratégie de test, environnements, reproductibilité | `backend/tests/conftest.py`, `.github/workflows/ci.yml` | Prêt — **expliciter l'écart SQLite local / PostgreSQL en CI** |
| 5.2 | Résultats de build et de tests | `validation_runs/2026-09-22_validation_summary.md` | Prêt : build **réussi**, suite backend **en échec** (594/3/6) |
| 5.3 | Analyse des échecs | E-01, E-02, E-03 | Prêt — **E-03 est une incohérence d'autorisation réelle** |
| 5.4 | Portes de qualité de la CI | `.github/workflows/ci.yml` | Prêt — distinguer configuré / exécuté |
| 5.5 | Livraison, déploiement, retour arrière | Compose, migration au démarrage | Partiel — aucun déploiement exécuté, aucun retour arrière |
| 5.6 | Validation de sécurité | `test_auth_security.py`, `test_rbac.py` | Partiel — **aucun test dynamique** |
| 5.7 | Performance, capacité, résilience | — | **Non exécutées** : à déclarer |
| 5.8 | Exploitation et observabilité | `/health`, sondes, `audit_logs` | Prêt — **absence de métriques, traces et alertes à déclarer** |
| 5.9 | Qualité du modèle de salaire | Artefact `salary_model_piqbit.p`, `audit_report.json` (2026-09-10) | Prêt : 8 modèles comparés, MAE test 402 TND, R² 0,891 |
| 5.10 | Limites et validations futures | `04_report_depth_gap_analysis.md`, G-01 à G-13 | Prêt |

Tableaux : matrice de tests, résultats datés, budget de bundle, comparaison des
modèles. Figure : flux de livraison (**produite**, `fig:delivery_flow`).

---

## Conclusion générale

Bilan objectif par objectif, contributions démontrées, limites, perspectives.
**Aucune preuve nouvelle.** Preuves : chapitres 1 et 5. `TODO: M-09`.

---

## Annexes

| Annexe | Contenu | État |
| --- | --- | --- |
| A | Inventaire des endpoints (173 routes) | Générable depuis le code |
| B | Modèle de données détaillé (25 tables) | Générable |
| C | Politique d'autorisation (`rbac_policy.csv`, expurgée) | Prête |
| D | Matrice de traçabilité complète | Partielle |
| E | Campagne de validation du 2026-09-22 | Prête |
| F | Inventaire des variables de configuration (`\.env.example`, **sans valeurs**) | Prête |

---

## Ordre de rédaction recommandé

1. Chapitres 3, 4 et 5 — la matière existe et est datée.
2. Chapitre 2 — après approbation du périmètre étendu.
3. Chapitre 1, introduction et conclusion — après M-05, M-09 à M-12.
4. Mise en forme LaTeX finale — après réception du gabarit institutionnel (M-03).

Avant toute rédaction des chapitres 1 et 2, **traiter les trois échecs de
tests** puis produire une **nouvelle campagne datée** : le chapitre 5 doit
refléter l'état livré, pas un état intermédiaire.
