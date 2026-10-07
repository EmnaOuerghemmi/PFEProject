# PIQBIT — Informations manquantes bloquantes

Statut : ouvert. Révision d'inspection : `c8e1bb7` (2026-09-15) **plus
modifications non committées** (78 fichiers modifiés, 5 supprimés,
17 non suivis au 2026-09-22). Date d'établissement : 2026-09-22.

Ce document liste **uniquement** ce qui ne peut pas être découvert depuis les
fichiers du dépôt et qui bloque ou contraint la rédaction. Tout le reste a été
relevé et consigné dans `01_project_report_spec.md` et `02_evidence_inventory.md`.

---

## 1. Métadonnées académiques et gabarit — bloquant

| # | Manque | Pourquoi c'est bloquant | Indice trouvé dans le dépôt (à confirmer, jamais à supposer) |
|---|---|---|---|
| M-01 | Titre officiel du rapport | Figure sur la couverture et dans les métadonnées PDF. | Aucun. Le dépôt ne porte qu'un nom de produit, « PIQBIT ». |
| M-02 | Établissement, filière, année universitaire | Détermine la classe LaTeX, la couverture, les signatures, le style bibliographique. | `Cahier_des_Charges_PIQBIT.docx` porte l'adresse `…@esprit.tn` de l'autrice. **Indice, pas une confirmation** : l'appartenance institutionnelle et le gabarit imposé doivent être confirmés. |
| M-03 | Gabarit LaTeX officiel (classe, fichiers imposés, révision) | `pfe_latex_conventions.md` fait primer le gabarit institutionnel sur toute recommandation. Sans lui, l'échafaudage reste provisoire. | Aucun fichier `.tex`, `.cls` ou `.sty` dans le dépôt. |
| M-04 | Langue du rapport et langues des résumés | Le dépôt est **bilingue** : commentaires, documentation et interface majoritairement en français ; noms de modules, docstrings et messages de commit partiellement en anglais. Le rapport doit trancher. | `DOCUMENTATION.md`, `backend/README.md`, `.github/workflows/ci.yml` en français ; `frontend/README.md` en anglais. |
| M-05 | Organisme d'accueil et limites de divulgation | Chapitre 1 entier (contexte, existant, besoins). | `backend/app/core/config.py` porte `COMPANY_NAME = "PIQBIT Lab"`, `COMPANY_ADDRESS = "Tunis, Tunisie"` et le **nom d'un gérant**. Ce sont des valeurs par défaut d'en-tête de contrat de travail, **pas** une preuve d'organisme d'accueil, et le nom du gérant ne doit pas être publié sans accord. |
| M-06 | Encadrants académique et professionnel | Couverture et remerciements. | Aucun. |
| M-07 | Style de citation imposé | Choix `biblatex`/`natbib`, tri, clés. | Aucun. |
| M-08 | Livrable attendu | La demande initiale laisse `<EXPECTED_DELIVERABLE>` non renseigné. Ce lot couvre plan + gabarits complétés + carte de preuves + campagne datée + analyse d'écart + échafaudage LaTeX provisoire ; la **rédaction des chapitres** attend M-01 à M-07. | — |

## 2. Contexte projet non déductible du code — bloquant pour le chapitre 1

| # | Manque | Impact |
|---|---|---|
| M-09 | Problématique réelle et situation existante chez le commanditaire | Le chapitre 1 ne peut pas être écrit. Le cahier des charges énonce des objectifs produit, pas un constat d'existant chiffré. |
| M-10 | Bénéficiaires réels et volumétrie attendue | Aucune exigence de capacité ne peut être posée ni validée. |
| M-11 | Méthode de gestion réellement suivie, et lequel des deux plannings fait foi | **Aucun sprint n'existe dans le dépôt.** Le projet est décrit en *phases*, et les deux sources se contredisent (C-08) : le cahier des charges §11 en donne **9** (fonctionnelles), `generate_gantt.py` en donne **5** (techniques). Les deux sont **prévisionnelles**, à partir du 2026-05-09. L'historique Git commence au 2026-07-08 par un « initial clean commit » et ne compte que 21 commits, dont aucun message ne mentionne sprint ni itération : **il ne peut pas servir de preuve du déroulement réel**. Sans confirmation, le rapport ne doit revendiquer ni Scrum, ni sprints, ni respect d'un planning. |
| M-12 | Statut réel des phases 8 et 9 du planning | Le cahier des charges les donne « en cours » et « prévu » au 2026-05-06. La CI et les images Docker existent depuis 2026-07-26/27 ; l'état actuel doit être confirmé, pas déduit. |

## 3. Autorisations de publication — bloquant pour les annexes et figures

| # | Manque | Impact |
|---|---|---|
| M-13 | Accord de publication des captures d'écran | Les 28 captures sont désormais **spécifiées** (`06_screenshot_plan.md` : chemin, contenu attendu, masquages) mais **aucune n'est prise**. Elles devront l'être sur le jeu de **démonstration** (`seed_demo.py`, comptes `@piqbit.demo`), jamais sur `backend/uploads/` (264 CV réels). L'accord porte sur la publication, pas sur la méthode : celle-ci est arrêtée. |
| M-14 | Accord sur la divulgation du nom de société, du gérant et des adresses | Voir M-05. |
| M-15 | Politique de conservation des preuves brutes | `validation_evidence_inventory.md` impose de stocker les preuves restreintes hors du paquet partageable ; l'emplacement doit être décidé. |

## 4. Éléments de méthode absents de la documentation réutilisable

| # | Manque | Traitement retenu |
|---|---|---|
| M-16 | `validation_runs/validation_summary_template.md` est **absent du dépôt** alors que `AGENTS.md` le référence. | Le gabarit a été reconstitué à partir du vocabulaire d'états et des rubriques de `validation_evidence_inventory.md`, et la campagne datée `validation_runs/2026-09-22_validation_summary.md` le suit. À remplacer si le gabarit d'origine est retrouvé. |

---

## Ce qui n'est **pas** manquant

Pour éviter des demandes inutiles : l'architecture, la pile technique et ses
versions, le modèle de données, les interfaces, les contrôles de sécurité, la
chaîne de livraison, le périmètre fonctionnel implémenté et une première
campagne de validation datée sont **tous établis depuis le dépôt** et consignés
dans `01_project_report_spec.md`, `02_evidence_inventory.md`,
`03_validation_evidence_inventory.md` et
`validation_runs/2026-09-22_validation_summary.md`.

**Ne sont plus manquants depuis le 2026-09-22 (soir) :**

- **Les neuf diagrammes.** Produits en TikZ (`report/diagrams/`), insérés dans
  les chapitres 2, 3 et 5, et compilés. Ils ne dépendaient d'aucune
  information extérieure : toute leur matière était dans le dépôt.
  Le planning prévisionnel est inséré au chapitre 1 avec une légende qui
  énonce explicitement qu'il ne prouve aucun déroulement réel (M-11).
- **Le mode opératoire des captures.** Les 28 captures sont spécifiées une par
  une dans `06_screenshot_plan.md`. Reste à les **prendre**, et à obtenir
  l'accord de publication (M-13) — deux choses distinctes.
