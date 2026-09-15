"""
Entraîne le modèle de prédiction de salaire PIQBIT sur le dataset marché tunisien
(`backend/datasets/tunisia_it_salaries.csv`) et sérialise le résultat au format
`piqbit_salary_v2` consommé par `SalaryPredictionService._predict_piqbit`.

Différences avec la v1 (qui ne prédisait qu'un point) :

1. **Cible multi-sortie** — le modèle apprend `[salary_min, salary_avg, salary_max]`
   au lieu du seul `salary_avg`. Le marché n'est pas un nombre, c'est une
   FOURCHETTE : la restituer telle quelle évite de comparer une demande à un
   point arbitraire (bug métier de la v1 : « écart demande / marché = −2400 »).
2. **Pondération par source** — le dataset mélange un barème de référence
   (178 lignes cohérentes) et 7 lignes d'enquête dont les fourchettes sont
   corrompues (cf. README du dataset). Elles sont conservées mais pondérées à
   `SURVEY_WEIGHT` pour qu'elles informent la forme du modèle sans tirer les
   prédictions vers le bas. Aucune modification du CSV n'est nécessaire.
3. **Table de bandes empiriques** — médianes (min/avg/max) par
   `titre × séniorité` puis `catégorie × séniorité`, sérialisées avec le modèle.
   Elles servent à l'inférence de garde-fou (bornage de la sortie ML) et de
   repli quand le titre est inconnu. C'est le volet « calibrage » du modèle :
   la forêt donne le point, la table garantit une enveloppe plausible.

Le vecteur de features est construit EXACTEMENT comme à l'inférence :
    [ one-hot(categories) ] + [ seniority_ordinal ] + [ experience_years ] + [ multi-hot(skill_vocab) ]

Usage :
    cd backend
    python scripts/train_salary_model.py
    # → écrit backend/salary_model_piqbit.p
"""
import csv
import pickle
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

# Doit rester aligné avec DecisionService/_guess_seniority (échelle ordinale 1..4).
SENIORITY_ORDINAL = {"junior": 1, "mid": 2, "senior": 3, "lead": 4}

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATASET = BACKEND_DIR / "datasets" / "tunisia_it_salaries.csv"
OUTPUT = BACKEND_DIR / "salary_model_piqbit.p"

# Taille du vocabulaire de compétences retenu (les plus fréquentes du marché).
SKILL_VOCAB_SIZE = 40

# Colonnes cibles, dans l'ordre du vecteur de sortie du modèle.
TARGETS = ("salary_min_tnd", "salary_avg_tnd", "salary_max_tnd")

# Les lignes du barème de référence font foi ; celles issues de l'enquête
# (fourchettes reconstruites à ±20 % d'une moyenne annuelle) sont dépondérées.
REFERENCE_SOURCE_PREFIX = "estimation_marche_TN_reference"
SURVEY_WEIGHT = 0.15


def _seniority_ordinal(label: str) -> int:
    return SENIORITY_ORDINAL.get(str(label).strip().lower(), 2)


def _tokenize_skills(raw: str) -> list[str]:
    return [s.strip().lower() for s in str(raw).split(",") if s.strip()]


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_vocab(rows: list[dict]) -> tuple[list[str], list[str]]:
    """Catégories (ordre one-hot) et vocabulaire de compétences (multi-hot)."""
    categories = sorted({r["category"].strip() for r in rows})
    skill_counter: Counter = Counter()
    for r in rows:
        for s in _tokenize_skills(r["top_skills"]):
            skill_counter[s] += 1
    skill_vocab = [s for s, _ in skill_counter.most_common(SKILL_VOCAB_SIZE)]
    return categories, skill_vocab


def build_features(row: dict, categories: list[str], skill_vocab: list[str]) -> list[float]:
    """Construit le vecteur de features d'une ligne, à l'identique de l'inférence."""
    category = row["category"].strip()
    vec = [1.0 if category == c else 0.0 for c in categories]

    vec.append(float(_seniority_ordinal(row["seniority"])))

    exp_min = float(row.get("experience_years_min") or 0)
    exp_max = float(row.get("experience_years_max") or exp_min)
    vec.append((exp_min + exp_max) / 2.0)

    skills = " ".join(_tokenize_skills(row["top_skills"]))
    for term in skill_vocab:
        vec.append(1.0 if term in skills else 0.0)
    return vec


def _row_weight(row: dict) -> float:
    """1.0 pour le barème de référence, `SURVEY_WEIGHT` pour l'enquête."""
    source = str(row.get("source", "")).strip()
    return 1.0 if source.startswith(REFERENCE_SOURCE_PREFIX) else SURVEY_WEIGHT


def build_bands(rows: list[dict]) -> tuple[dict, dict, dict]:
    """
    Bandes de marché empiriques, en ne retenant que le barème de référence.

    Retourne trois tables :
      - `title_bands`   : "titre|ordinal_séniorité" -> [min, avg, max]
      - `category_bands`: "catégorie|ordinal_séniorité" -> [min, avg, max]
      - `title_experience`: "titre|ordinal" -> [exp_min, exp_max] (bornes du palier)

    La médiane (et non la moyenne) rend la table insensible à une ligne aberrante.
    """
    by_title: dict[str, list[list[float]]] = defaultdict(list)
    by_category: dict[str, list[list[float]]] = defaultdict(list)
    exp_by_title: dict[str, list[list[float]]] = defaultdict(list)

    for r in rows:
        if not str(r.get("source", "")).startswith(REFERENCE_SOURCE_PREFIX):
            continue
        try:
            triple = [float(r[t]) for t in TARGETS]
        except (KeyError, TypeError, ValueError):
            continue
        sen = _seniority_ordinal(r["seniority"])
        title_key = f"{r['title'].strip().lower()}|{sen}"
        cat_key = f"{r['category'].strip()}|{sen}"
        by_title[title_key].append(triple)
        by_category[cat_key].append(triple)
        exp_by_title[title_key].append([
            float(r.get("experience_years_min") or 0),
            float(r.get("experience_years_max") or 0),
        ])

    def _median_rows(bucket: dict[str, list[list[float]]]) -> dict[str, list[float]]:
        return {
            key: [round(statistics.median(col)) for col in zip(*triples)]
            for key, triples in bucket.items()
        }

    return _median_rows(by_title), _median_rows(by_category), _median_rows(exp_by_title)


def main() -> None:
    if not DATASET.exists():
        raise SystemExit(f"Dataset introuvable : {DATASET}")

    rows = load_rows(DATASET)
    print(f"Dataset chargé : {len(rows)} lignes depuis {DATASET.name}")

    categories, skill_vocab = build_vocab(rows)
    print(f"Catégories ({len(categories)}) : {categories}")
    print(f"Compétences retenues ({len(skill_vocab)}) : {skill_vocab}")

    X, Y, W, title_to_category = [], [], [], {}
    for r in rows:
        try:
            targets = [float(r[t]) for t in TARGETS]
        except (KeyError, TypeError, ValueError):
            continue
        X.append(build_features(r, categories, skill_vocab))
        Y.append(targets)
        W.append(_row_weight(r))
        title_to_category[r["title"].strip().lower()] = r["category"].strip()

    X = np.array(X, dtype=float)
    Y = np.array(Y, dtype=float)
    W = np.array(W, dtype=float)
    n_survey = int((W < 1.0).sum())
    print(f"Pondération : {len(W) - n_survey} lignes de référence (1.0) · "
          f"{n_survey} lignes d'enquête ({SURVEY_WEIGHT})")

    X_train, X_test, Y_train, Y_test, W_train, _ = train_test_split(
        X, Y, W, test_size=0.2, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=1,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, Y_train, sample_weight=W_train)

    pred = model.predict(X_test)
    per_target = {
        name: {
            "mae": round(float(mean_absolute_error(Y_test[:, i], pred[:, i])), 1),
            "r2": round(float(r2_score(Y_test[:, i], pred[:, i])), 4),
        }
        for i, name in enumerate(TARGETS)
    }
    print("\nÉvaluation (hold-out 20%) :")
    for name, m in per_target.items():
        print(f"  {name:<16} MAE = {m['mae']:>7.1f} TND | R² = {m['r2']:.3f}")

    # Ré-entraînement final sur 100% des données pour le modèle livré.
    model.fit(X, Y, sample_weight=W)

    title_bands, category_bands, title_experience = build_bands(rows)
    print(f"\nBandes empiriques : {len(title_bands)} (titre × séniorité) · "
          f"{len(category_bands)} (catégorie × séniorité)")

    payload = {
        "format": "piqbit_salary_v2",
        "model": model,
        "categories": categories,
        "title_to_category": title_to_category,
        "skill_vocab": skill_vocab,
        "targets": list(TARGETS),
        "title_bands": title_bands,
        "category_bands": category_bands,
        "title_experience": title_experience,
        "currency": "TND",
        "period": "mensuel_brut",
        "metrics": per_target,
        "n_samples": len(X),
        "survey_weight": SURVEY_WEIGHT,
    }
    with open(OUTPUT, "wb") as f:
        pickle.dump(payload, f)
    print(f"\nModèle sérialisé -> {OUTPUT}")
    print("Format : piqbit_salary_v2 (fourchette min/avg/max + bandes de calibrage)")


if __name__ == "__main__":
    main()
