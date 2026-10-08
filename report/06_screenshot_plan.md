# PIQBIT — Plan de captures d'écran

Date : **2026-09-22**. Complète `02_evidence_inventory.md` (section « Preuves de
captures d'écran »), qui listait les noms de fichiers sans mode opératoire.

Ce document donne, pour chaque capture : le **nom de fichier**, le **titre de
figure** à reprendre tel quel dans le rapport, le **chemin pour l'obtenir**, ce
qui **doit être visible**, et ce qui **doit être masqué**.

---

## 0. Avant toute capture — obligatoire

### 0.1 Jeu de données

Les captures se prennent **exclusivement** sur le jeu de démonstration :

```bash
python backend/scripts/seed_demo.py
```

Tous les comptes créés portent le suffixe `@piqbit.demo`, mot de passe
`Demo1234!`. Comptes utiles : `rh1@piqbit.demo`, `candidat1@piqbit.demo`.

> **Interdiction stricte.** Ne jamais capturer un écran alimenté par
> `backend/uploads/` : ce répertoire contient **264 CV réels**. Une seule
> capture d'un nom, d'une adresse ou d'un numéro de téléphone réel suffit à
> rendre le rapport non diffusable, et la règle du projet est explicite :
> aucune donnée personnelle de CV ne sort, ni en journal, ni en figure.

### 0.2 Préparation de la fenêtre

| Point | Réglage |
| --- | --- |
| Largeur de fenêtre | 1440 px (les mises en page sont conçues pour cette largeur) |
| Zoom navigateur | 100 % — un zoom autre fausse les proportions d'une figure à l'autre |
| Thème | Clair, pour rester lisible à l'impression |
| Barre d'onglets | Masquée ou recadrée |
| Notifications système | Désactivées (mode concentration) |

### 0.3 Contrôle de rédaction — à repasser sur **chaque** fichier

- [ ] Aucun nom, e-mail, téléphone ou adresse réels (tout doit finir en `@piqbit.demo`)
- [ ] Aucune barre d'URL montrant `localhost:4200` avec un **jeton** dans le chemin
      (`/interview/confirm/…`, `/test/…`, `/contract/sign/…`)
- [ ] Aucun chemin de poste de travail visible (`E:\PIQBIT\…`, `C:\Users\…`)
- [ ] Aucun secret TOTP réel, aucune clé d'API, aucun en-tête `Authorization`
- [ ] Aucun historique ni favori de navigateur
- [ ] Aucune notification système dans le cadre

### 0.4 Format et emplacement

- Format **PNG**, sans compression destructrice.
- Emplacement : **`report/assets/screenshots/`**.
- Nom de fichier : exactement celui de la colonne « Fichier » ci-dessous.
  Les noms sont déjà référencés dans `02_evidence_inventory.md` ; les changer
  casserait la traçabilité.

### 0.5 Insertion dans le rapport

Une commande dédiée est disponible (définie dans `config/commands.tex`) :

```latex
\pqscreenshot{nom_du_fichier}{Titre de la figure.}{fig:cle}
```

---

## 1. Parcours candidat — chapitre 4

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| C-1 | `job_list_public.png` | Catalogue public des offres, avec recherche et filtres | `/frontoffice/jobs`, **déconnecté** | La liste, la barre de recherche, les filtres actifs | — |
| C-2 | `job_detail_apply.png` | Fiche d'offre et formulaire de candidature | `/frontoffice/job/:id` puis « Postuler » | Les compétences requises, la modale de candidature avec le dépôt de CV | Nom du fichier CV s'il est réel |
| C-3 | `my_applications_status.png` | Suivi des candidatures par le candidat | `/frontoffice/applications` | Au moins trois statuts différents, pour montrer le cycle de vie | — |
| C-4 | `application_score_detail.png` | Restitution de l'analyse de CV au candidat | `/frontoffice/application/:id` | L'anneau de score et la section « Comment nous avons lu votre CV » | — |
| C-5 | `interview_confirm_public.png` | Page publique de confirmation de créneau | Lien reçu, `/interview/confirm/:token` | Les créneaux proposés et le bouton de confirmation | **Le jeton dans l'URL — recadrer au-dessus de la barre d'adresse** |
| C-6 | `test_public_session.png` | Passage du test technique, minuteur visible | `/test/:token` | Le minuteur, une question, la progression | **Le jeton dans l'URL** |

## 2. Parcours recruteur et RH — chapitre 4

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| R-1 | `recruitment_ranking.png` | Classement des candidats pour une offre | `/admin/recruitment` | Le classement trié par score, plusieurs candidats de démonstration | — |
| R-2 | `cv_analysis_breakdown.png` | Décomposition d'un score de candidat | `/admin/recruitment`, fiche d'un candidat | Les sous-scores (compétences, expérience, formation) et leur pondération | — |
| R-3 | `semantic_search_results.png` | Recherche sémantique de profils | Page de recherche sémantique du back-office | Une requête en langage naturel et ses résultats classés | — |
| R-4 | `interview_manager_slots.png` | Gestion des entretiens : cartes, statuts, pagination | `/admin/interviews` | Les quatre statuts si possible, la pagination, le bandeau Google Calendar | — |
| R-5 | `interview_scheduler_recruiter.png` | Planification d'un entretien avec recruteur assigné | `/admin/applications`, action « Planifier un entretien » | Les créneaux proposés **et le sélecteur de recruteur assigné** | Adresses réelles dans la liste déroulante |
| R-6 | `assessment_review.png` | Correction et résultats d'un test technique | `/admin/assessment` | Une session terminée, son score, le détail des réponses | — |
| R-7 | `salary_prediction_form.png` | Prédiction salariale et intervalle proposé | `/admin/negotiation` | Les variables d'entrée et la fourchette prédite | — |
| R-8 | `negotiation_live_log.png` | Journal de négociation en temps réel | `/admin/negotiation`, négociation ouverte | Plusieurs tours successifs, montants et messages | — |
| R-9 | `contract_sign_certificate.png` | Contrat signé et certificat de signature | `/admin/contracts`, contrat signé | L'identifiant de certificat, l'empreinte, la piste d'audit | **Signature manuscrite réelle ; IP réelle** |
| R-10 | `cag_assistant_sources.png` | Assistant extractif et sources citées | `/admin/assistant` | Une réponse **avec ses sources** — c'est ce qui distingue l'extractif du génératif | — |

## 3. RH interne et pilotage — chapitre 4

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| H-1 | `employees_list.png` | Répertoire des employés | `/admin/employees` | La liste, les départements, les statuts | Salaires réels s'ils apparaissent |
| H-2 | `budget_department.png` | Budget par département et imputation des dépenses | `/admin/budget` | L'enveloppe, les dépenses imputées, le reste à engager | — |
| H-3 | `career_plan.png` | Plan de carrière d'un employé | `/admin/career` | Les objectifs et les jalons | — |
| H-4 | `reports_snapshot.png` | Rapport de synthèse et instantané archivé | `/admin/reports` | Les indicateurs et la date de l'instantané | — |
| H-5 | `decision_board.png` | Tableau d'aide à la décision | `/admin/decision` | Les candidats comparés et les critères | — |
| H-6 | `notifications_realtime.png` | Notifications diffusées en temps réel | N'importe quelle page du back-office, panneau ouvert | Plusieurs notifications, dont une non lue | — |

## 4. Administration — chapitre 4

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| A-1 | `backoffice_dashboard.png` | Tableau de bord du back-office | `/admin/dashboard` | Les indicateurs et au moins un graphique alimenté | — |
| A-2 | `users_management_roles.png` | Gestion des comptes et attribution des rôles | `/admin/users` | Les quatre rôles représentés : `ADMIN`, `RH`, `RECRUTEUR`, `CANDIDAT` | Adresses réelles |
| A-3 | `audit_log_trail.png` | Journal d'audit : acteur, action, cible | `/admin/users`, onglet d'audit | Plusieurs entrées horodatées d'acteurs différents | Adresses IP réelles |

## 5. Sécurité — chapitre 5

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| S-1 | `2fa_totp_enrollment.png` | Activation du second facteur : QR et codes de secours | `/frontoffice/profile`, bouton d'activation | L'écran d'enrôlement complet | **Le QR code et le secret TOTP — les flouter ou utiliser un secret jetable** |
| S-2 | `rbac_denied_403.png` | Refus d'autorisation sur une route réservée | Se connecter en `CANDIDAT`, viser une route `/admin/…` | Le refus effectif (écran ou réponse `403`) | — |
| S-3 | `account_lockout.png` | Verrouillage de compte après tentatives répétées | Écran de connexion, mots de passe erronés répétés | Le message de verrouillage | Adresse réelle |

## 6. Livraison et exécution — chapitre 5

| # | Fichier | Titre de figure | Où | Doit montrer | Masquer |
| --- | --- | --- | --- | --- | --- |
| L-1 | `ci_workflow_summary.png` | Résumé d'exécution de la chaîne d'intégration | GitHub, onglet *Actions*, une exécution | Les deux travaux, leur durée, leur issue | Nom du dépôt privé si la divulgation n'est pas accordée |
| L-2 | `ci_test_failure_detail.png` | Détail des trois échecs de la campagne du 22 septembre 2026 | Journal du travail « Backend — tests » | Les trois échecs **nommés** — ils sont analysés au chapitre 5, les cacher contredirait le texte | Chemins de poste de travail |
| L-3 | `docker_compose_healthy.png` | Pile de conteneurs démarrée et saine | Terminal, `docker compose --profile app ps` | Les quatre services et leur état `healthy` | Chemin du répertoire dans l'invite |
| L-4 | `health_endpoint.png` | Réponse du point de contrôle de santé | `GET /health` | Le corps JSON et le code `200` | — |
| L-5 | `bundle_budget_warning.png` | Avertissements de budget au build de production | Terminal, `npm run build -- --configuration production` | Les **quatre avertissements** et la taille du bundle initial | Chemin du répertoire |

---

## 7. Récapitulatif

**28 captures**, dont les 16 déjà nommées dans `02_evidence_inventory.md` et
12 ajouts qui couvrent des sections du chapitre 4 restées sans preuve visuelle
(test technique, sémantique, assistant extractif, prédiction salariale, RH
interne, rapports, décision, notifications, audit, verrouillage, et les deux
captures de livraison).

**Ordre de production conseillé.** Groupes 1 et 2 d'abord : ils portent la
démonstration fonctionnelle et sont les plus longs à mettre en scène. Groupe 6
en dernier, **après** correction des trois échecs de tests — la capture L-2
devra alors être reprise, puisque le chapitre 5 doit refléter l'état livré.

**Deux captures resteront volontairement en échec** si elles sont prises
aujourd'hui : L-2 (trois tests échoués) et L-5 (budget de bundle dépassé). Ce
sont des constats datés, pas des défauts de mise en scène : ils figurent au
rapport avec leur analyse.
