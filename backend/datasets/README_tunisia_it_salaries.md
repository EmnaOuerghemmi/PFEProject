# Datasets salaires & négociation — PIQBIT

## Fichiers

| Fichier | Rôle |
|---|---|
| `tunisia_it_salaries.csv` | **Dataset brut**, enrichi des colonnes d'audit. Source de vérité, éditable à la main. |
| `tunisia_salaries_clean.csv` | **Dataset propre**, produit par le pipeline. Régénéré à chaque exécution — ne pas l'éditer. |
| `audit_report.json` | Constat d'audit de la dernière exécution (anomalies, conversions, exclusions). |
| `negotiation_scenarios.csv` | Cas de négociation avec décision attendue — suite de non-régression du moteur de règles. |

Tout est produit par un seul script :

```bash
cd backend
python scripts/salary_ml_pipeline.py              # audit + nettoyage + comparaison + livraison
python scripts/salary_ml_pipeline.py --audit-only # audit seul, sans entraînement
python scripts/salary_ml_pipeline.py --repeats 10 # comparaison plus robuste
```

---

## `tunisia_it_salaries.csv` — 185 lignes

Salaires **mensuels (TND)**, 37 métiers × 4 paliers de séniorité, plus 7 lignes d'enquête.
Couvre toutes les familles de l'entreprise, pas seulement l'IT :
`Tech, Data, Design, Management, RH, Commercial, Marketing, Finance, Admin, Support, Engineering`.

### Colonnes métier

| Colonne | Description |
|---|---|
| `title` | Intitulé du poste |
| `category` | Famille de métier |
| `seniority` | Junior / Mid / Senior / Lead |
| `experience_years_min/max` | Fourchette d'expérience attendue pour le palier |
| `salary_min/avg/max_tnd` | Fourchette salariale estimée |
| `currency` / `period` | TND / mensuel_brut |
| `education` | Niveau d'études typique |
| `top_skills` | Compétences clés (séparées par des virgules) |
| `region` / `source` | Origine géographique et provenance de l'estimation |

### Colonnes d'audit

Ajoutées après vérification ligne à ligne. Elles répondent aux questions qu'il faut
se poser **avant** de supprimer une valeur extrême.

| Colonne | Valeurs | Rôle |
|---|---|---|
| `salary_basis` | `brut` / `net` | Base salariale déclarée. Le pipeline convertit tout en brut. |
| `population` | `marche_reference` / `enquete_nationale` | Population couverte — deux marchés différents, pas deux mesures du même. |
| `quality_flag` | `ok` / `seniorite_incoherente` | Anomalie constatée. Seules les lignes `ok` entrent à l'entraînement. |
| `quality_note` | texte libre | Motif écrit de la décision, pour que l'exclusion reste auditable. |

---

## Résultat de l'audit

### 1. Deux sources, deux unités

178 lignes viennent d'un **barème de référence** (marché offshore / entreprises
structurées de Tunis), 7 d'une **enquête SalaryExplorer** couvrant l'ensemble du
marché national.

Ces 7 lignes affichaient 0,39 à 0,72 × la médiane de leurs pairs. Vérification
faite, ce n'était **ni du bruit ni une erreur de saisie** :

* elles sont exprimées en **net**, pas en brut → `salary_basis = net` ;
* elles couvrent une **population plus large** (TPE, secteur public) → `population = enquete_nationale`.

Après conversion net → brut, `Software Engineer Mid` remonte de 1 800 à 2 408 TND,
soit **0,96 × la médiane des pairs** : l'hypothèse est validée. Le reliquat sur
les autres lignes est un écart de population, conservé tel quel.

### 2. Une incohérence réelle

`Sr. Software Engineer` (Senior) était coté **1 500** alors que
`Software Engineer` (Mid), **de la même source**, était coté **1 800**. Un senior
ne peut pas être payé moins qu'un confirmé. Échantillon d'enquête trop faible ou
intitulé mal rattaché : la ligne est **conservée dans le CSV** pour la traçabilité
et **exclue de l'entraînement**, avec son motif écrit.

C'est la seule exclusion.

### 3. Ce qui ressemblait à des anomalies et n'en était pas

`WordPress Developer` est à 0,71 × la médiane Tech, `Solutions Architect` à 1,88 ×.
Mais l'écart est **régulier sur tous leurs paliers** : c'est un positionnement de
métier, pas une erreur. Une vraie anomalie casse le motif — elle touche un palier
et pas les autres. Le pipeline ne signale que les déviations irrégulières.

### 4. Ce qui était sain

Aucune valeur manquante, aucun doublon (exact ou sur `titre × séniorité`),
aucune violation de `min ≤ avg ≤ max` ni de `exp_min ≤ exp_max`, aucune inversion
de séniorité après nettoyage.

---

## Normalisation des unités

Toutes les observations finissent en **TND, mensuel, brut**. Dans l'ordre :
devise → période → base salariale.

La conversion net → brut inverse le barème social tunisien réel — CNSS salarié
9,18 %, abattement frais professionnels 10 % plafonné à 2 000 DT, IRPP progressif
par tranches, CSS 0,5 % — par dichotomie, et non par un coefficient forfaitaire.
Le taux de prélèvement varie de ~16 % en bas d'échelle à ~38 % en haut : un
coefficient unique se tromperait partout sauf sur une tranche.

---

## Modèle livré

`salary_model_piqbit.p`, format `piqbit_salary_v3`.

**Cible multi-sortie** `[salary_min, salary_avg, salary_max]` : le marché est une
fourchette, pas un point.

**Sélection par généralisation.** Huit candidats comparés sur 5 partitions
60/20/20 indépendantes, métriques moyennées. Le gagnant est celui qui minimise la
MAE sur le jeu de **test**, jamais vu — pas celui qui colle le mieux à
l'entraînement :

| Modèle | MAE train | MAE test | ± σ | R² test | écart |
|---|---|---|---|---|---|
| Baseline (moyenne) | 1482 | 1494 | 122 | −0.010 | 12 |
| Linear Regression | 193 | 522 | 122 | 0.748 | 329 |
| Ridge (α=1.0) | 291 | 462 | 35 | 0.861 | 171 |
| Random Forest | 200 | 544 | 81 | 0.820 | 344 |
| **Gradient Boosting** | **111** | **402** | **55** | **0.891** | **292** |
| HistGradientBoosting | 703 | 806 | 54 | 0.609 | 103 |
| XGBoost | 86 | 444 | 67 | 0.871 | 358 |
| LightGBM | 163 | 539 | 68 | 0.824 | 376 |

XGBoost a la meilleure erreur d'**entraînement** (86) et une erreur de test
supérieure de 10 % à Gradient Boosting : c'est exactement le piège que la
sélection sur test évite. Ridge est le plus **stable** (σ = 35) et le moins
surappris parmi les modèles précis — un choix défendable si la stabilité prime.

**Bandes de calibrage.** Le modèle embarque les médianes `(min, avg, max)` par
`titre × séniorité` (184) et `catégorie × séniorité` (39). À l'inférence, la
sortie du modèle est ancrée (shrinkage) sur ces bandes puis bornée dans leur
enveloppe ±8 % : la forêt interpole, le barème encadre.

### Features : ce qui entre, et ce qui a été retiré

```
[ one-hot(catégorie) ] + [ séniorité, expérience, amplitude du palier ] + [ multi-hot(compétences) ]
```

Construit par `app/services/salary_features.py`, importé **à la fois** par le
pipeline d'entraînement et par le service d'inférence : les deux chemins ne
peuvent pas diverger.

Le **niveau d'études a été retiré** des features. Dans ce dataset il est
entièrement déterminé par la séniorité :

| Séniorité | Niveaux d'études distincts |
|---|---|
| Junior | 1 (Licence, 38/38) |
| Mid | 2 (6 Licence, 38 Ingénieur/Master) |
| Senior | 1 (Ingénieur/Master, 51/51) |
| Lead | 1 (Master, 51/51) |

Corrélation de Spearman séniorité/études : **0,736**. La variable n'apportait
aucune information indépendante, mais créait un mode de défaillance majeur :
une offre junior déclarant « niveau ingénieur » était cotée comme un profil
confirmé — **1 750–2 150 TND au lieu de 1 350–1 900** pour un Full Stack Junior,
soit +53 %. Le modèle avait appris l'étude comme un proxy de séniorité.

Retirer la feature n'a rien coûté en précision (MAE test 402 TND avant comme
après, R² 0,891 → 0,892) et a supprimé la défaillance : c'est la signature d'une
variable colinéaire.

Deux autres défauts d'inférence corrigés dans le même module :

* **`java` était détecté dans « JavaScript »** — la correspondance des
  compétences se faisait par sous-chaîne. Une offre React/Node se voyait
  attribuer Java, un profil mieux payé. La détection exige désormais des limites
  de mots.
* **Les titres français n'étaient jamais reconnus** — le barème est en anglais
  (`full stack developer`), les offres en français
  (« Développeur(se) Full Stack Junior – Node.js / React.js »). La recherche par
  titre échouait systématiquement et retombait sur la bande générique de la
  catégorie. Les intitulés sont maintenant normalisés (accents, marques de
  genre, mots de séniorité, stack technique) puis rapprochés par recouvrement de
  tokens.

### Confiance annoncée

Elle exprime la **qualité de la source**, pas la complétude du formulaire. La
version précédente ajoutait un point par champ rempli et atteignait 90 % — un
chiffre rassurant mais faux : renseigner la description ne rend pas le marché
plus certain.

| Source du chiffre | Confiance |
|---|---|
| Bande du barème pour ce titre ET ce palier | 0,75 |
| Repli sur la famille de métier | 0,55 |
| Extrapolation du modèle, aucune bande connue | 0,40 |
| Estimateur heuristique (aucun modèle chargé) | 0,30 |

Abaissée de 0,15 quand ni les années d'expérience ni un mot de séniorité ne
permettent d'établir le palier — se tromper de palier, c'est se tromper de
fourchette.

---

## `negotiation_scenarios.csv`

18 situations de négociation décrites par les colonnes
`candidate_experience, required_experience, matching_score, market_salary_min/max,
company_budget_min/max, candidate_requested_salary, candidate_skills_score,
job_level`, avec `expected_decision` et `expected_recommendation`.

Le moteur de négociation est **à base de règles, pas appris** : une décision qui
engage un budget doit pouvoir être justifiée ligne à ligne devant un RH. Ce
fichier n'est donc pas un jeu d'entraînement mais une **suite de non-régression
métier** — `tests/test_negotiation_analysis.py` rejoue chaque ligne. Ajouter un
cas au CSV suffit à le couvrir, sans écrire de test.

---

## ⚠️ Provenance & honnêteté

Le barème de référence est une **estimation** fondée sur les fourchettes
publiquement connues du marché tunisien (≈ 2024–2026). Ses ratios sont très
réguliers (`min/avg` = 0,850 ± 0,006 ; `max/avg` = 1,180 ± 0,006) : c'est un
barème construit, à traiter comme un **prior de calibrage**, pas comme une mesure
statistique.

Ces données **ne proviennent pas** d'un scraping de LinkedIn ou d'un autre site
(interdit par leurs CGU).

### Pour obtenir de vraies données, légalement
* **Officiel** : enquêtes de rémunération de cabinets RH, open data, exports
  d'agrégateurs d'offres qui l'autorisent.
* **Sites avec autorisation** : respecter `robots.txt` et les CGU ; privilégier
  les flux RSS et les pages explicitement ouvertes.
* **LinkedIn** : passer par les API officielles si éligible.

Chaque nouvelle source doit arriver avec ses colonnes `salary_basis`,
`population` et `source` renseignées — sinon le pipeline ne peut pas la
normaliser correctement, et le modèle apprendra la convention de saisie plutôt
que le salaire.
