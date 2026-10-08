# PIQBIT — Analyse d'écart de profondeur académique

Statut : **gabarit `report_depth_gap_analysis.md` complété**.
Date de revue : **2026-09-22**. Révision revue : `c8e1bb7` + arbre de travail
modifié. Révision du rapport revue : **aucune prose de chapitre n'existe
encore** ; la revue porte donc sur la **matière disponible**, pas sur un
brouillon.

## Référence utilisée

Référentiel : les rubriques de `pfe_report_spec_refined.md` §7 et §12, et celles
de `pfe_report_spec_project_template.md`. **Aucun rapport tiers n'a été consulté
ni utilisé comme source de contenu.** `TODO:` substituer le barème officiel de
l'établissement dès qu'il est connu (M-02, M-03) — il prime sur ce référentiel.

---

## Comparaison structurelle

| Domaine | Profondeur académique attendue | État actuel du projet | Action requise |
| --- | --- | --- | --- |
| Contexte et cadrage | Organisme, existant, problématique, contribution, objectifs, périmètre, planification | **Insuffisant.** Objectifs et périmètre existent (cahier des charges §1, §10) ; le planning est **prévisionnel** (`gantt_diagram.png`). Il manque l'organisme, l'existant et une problématique argumentée. L'historique Git (21 commits depuis le 2026-07-08) ne peut pas étayer un récit de déroulement. | Obtenir M-05, M-09, M-10, M-11, M-12. **Bloquant** pour le chapitre 1. |
| Exigences | Acteurs, exigences fonctionnelles et non fonctionnelles mesurables, cas d'utilisation, critères d'acceptation, traçabilité | **Partiel.** Le cahier des charges v1.0 fournit 4 acteurs, ~24 exigences identifiées (AUTH/OFF/CAND) et 11 NFR avec critères. Mais il couvre **une fraction** de ce qui est implémenté : 13 capacités majeures n'ont aucun identifiant d'exigence (EXT-01 … EXT-13). Aucun cas d'utilisation formalisé. | Faire approuver le périmètre étendu, convertir `EXT-nn` en `FR-<DOMAINE>-<NUM>`, écrire les critères d'acceptation manquants, formaliser 4 à 6 cas d'utilisation principaux. |
| Architecture et conception | Contexte, logique, données, dynamique, sécurité, déploiement, décisions technologiques | **Matière solide, restitution nulle.** Tous les constats sont établis (`02_evidence_inventory.md`), **mais aucun diagramme n'existe** et aucune décision n'est formalisée en registre. | Produire les 8 diagrammes listés. Rédiger 6 à 8 fiches de décision avec alternatives et critères (voir ci-dessous). |
| Implémentation | Récit par sous-système, frontières de modules, décisions, captures, difficultés | **Matière très riche, restitution nulle.** Le code porte des justifications écrites de première main (conversion net→brut par dichotomie, retrait de la variable « niveau d'études » colinéaire, détection de `java` dans « JavaScript », titres français non reconnus, dérive de schéma, ports PostgreSQL sous Windows, jetons de réflexion Gemini). **Aucune capture d'écran n'existe.** | Sélectionner 5 à 7 difficultés techniques réelles et les rédiger (problème → diagnostic → décision → preuve). Produire les captures sur jeu de démonstration. |
| Validation et exploitation | Build, tests, livraison, sécurité, observabilité, résilience, limites, preuves datées | **Partiel et honnête.** Une campagne datée existe (2026-09-22) : build frontend **réussi**, suite backend **en échec** (594/3/6). Non couverts : E2E, performance, résilience, sécurité dynamique, déploiement exécuté, observabilité (**inexistante**). | Traiter les 3 échecs puis **re-tester et redater**. Exécuter les tests frontend. Capturer au moins une construction et un démarrage de pile. Déclarer explicitement tout le reste en limitation. |
| Conclusion | Bilan par objectif, contributions, limites, perspectives, sans preuve nouvelle | **Non commencé** — dépend de la confirmation des objectifs (M-09). | Rédiger en dernier, en reprenant objectif par objectif les résultats datés du chapitre 5. |
| Annexes | Inventaires, configurations, tableaux étendus, preuves référencées depuis le texte | **Non commencé**, mais la matière existe : inventaire des 173 routes, 25 tables, 18 migrations, politique RBAC, matrice de tests. | Prévoir : A — inventaire des endpoints ; B — modèle de données ; C — politique d'autorisation ; D — matrice de traçabilité ; E — campagne de validation datée. |

---

## Manque spécifique : registre de décisions

Le référentiel exige de justifier les choix significatifs par alternatives et
critères. Les décisions suivantes sont **techniquement établies** mais **non
argumentées** sous forme académique. Chacune doit devenir une fiche de décision.

| # | Décision constatée | Ce qu'il faut ajouter |
| --- | --- | --- |
| D-01 | Alembic comme source unique du schéma, à la place de `create_all` | Le problème résolu (dérive entre environnements), l'alternative écartée, et le garde-fou de CI qui la rend effective |
| D-02 | Autorisation externalisée dans une politique Casbin plutôt que des contrôles dans les endpoints | Critères : auditabilité, refus par défaut, revue en une seule lecture. **Mentionner honnêtement la limite révélée par l'échec E-03** |
| D-03 | Dégradation gracieuse systématique (embeddings, pgvector, visioconférence, modèle ML, LLM) | En faire une **propriété d'architecture transversale**, avec son coût : des chemins de repli moins testés |
| D-04 | Sélection du modèle de salaire sur l'erreur de **test**, pas d'entraînement | Justifier par les 8 modèles comparés sur 5 partitions ; expliquer pourquoi XGBoost, meilleur à l'entraînement, a été écarté |
| D-05 | Retrait de la variable « niveau d'études » des caractéristiques | Colinéarité avec la séniorité (Spearman 0,736), mode de défaillance supprimé, coût nul en précision |
| D-06 | Assistant **extractif** (CAG) plutôt que génératif | Critère : impossibilité d'hallucination, traçabilité de la source, absence de dépendance externe payante |
| D-07 | Signature électronique auto-hébergée plutôt que service tiers | Critères : coût, souveraineté des données, piste d'audit ; **limites juridiques à énoncer franchement** |
| D-08 | Origine unique via nginx plutôt que CORS entre deux origines | Conséquence : image frontend identique quel que soit le domaine |

---

## Améliorations déjà acquises

Uniquement ce qui est fait :

- Une **campagne de validation datée et reproductible** existe
  (`validation_runs/2026-09-22_validation_summary.md`), avec ses échecs publiés.
- La **carte de preuves** couvre architecture, diagrammes, captures, validation
  et traçabilité (`02_evidence_inventory.md`).
- Les **conflits entre sources** sont identifiés et arbitrés (C-01 à C-07),
  au lieu d'être silencieusement résolus.
- Les **règles de redaction** sont explicites et rattachées à des fichiers réels
  du dépôt.
- La **traçabilité** exigences → implémentation → tests est amorcée pour les
  exigences du cahier des charges et pour 13 capacités hors cahier des charges.

---

## Écarts restants

| # | Écart | Preuve ou décision nécessaire pour le lever |
| --- | --- | --- |
| G-01 | Métadonnées académiques et gabarit inconnus | M-01 à M-08 |
| G-02 | Contexte, problématique et existant absents | M-09, M-10 |
| G-03 | Méthode de gestion non établie | M-11 — **ne pas revendiquer Scrum sans preuve** |
| G-04 | Aucun diagramme | Produire les 8 diagrammes de `02_evidence_inventory.md` |
| G-05 | Aucune capture d'écran | Jeu de démonstration + contrôle de redaction |
| G-06 | 3 échecs de tests non traités, dont une incohérence d'autorisation | Corriger, puis **nouvelle campagne datée** |
| G-07 | Tests frontend, E2E, performance, résilience, sécurité dynamique non exécutés | Exécuter, ou déclarer en limitation |
| G-08 | Chemin `pgvector` natif jamais validé | Une exécution ciblée contre PostgreSQL + extension `vector` |
| G-09 | Aucune bibliographie | Constituer et **consulter indépendamment** chaque source |
| G-10 | 13 capacités sans identifiant d'exigence approuvé | Approbation du périmètre étendu |
| G-11 | Aucune analyse statique Python, alors que le projet impose du code typé | Décider : outiller, ou déclarer en limitation |
| G-12 | Absence de TLS, de coffre à secrets, de sauvegarde éprouvée et d'observabilité | À porter en limitations et perspectives, jamais à passer sous silence |
| G-13 | Rapport ancré sur un arbre de travail modifié | Committer et réancrer sur une révision stable |

---

## Contrôle de complétude

- Chaque mention « fait » ci-dessus renvoie à un fichier produit et inspectable.
- La revue porte sur l'état du **2026-09-22** et le mentionne.
- Le référentiel a influencé la **structure** uniquement ; aucun contenu tiers
  n'a été repris.
- Les écarts G-01 à G-13 sont repris comme `TODO` dans
  `01_project_report_spec.md` et `00_missing_information.md`, et alimenteront la
  section « Limites » du rapport.
- **Aucune validation non exécutée n'est présentée comme réussie.**
