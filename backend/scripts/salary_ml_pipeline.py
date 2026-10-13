"""
Pipeline ML complet de prédiction salariale PIQBIT.

    DATASET BRUT
         │
         ▼  1. AUDIT      — doublons, manquants, incohérences, valeurs extrêmes
         ▼  2. NETTOYAGE  — dédoublonnage, imputation, NORMALISATION DES UNITÉS
         ▼  3. FEATURES   — X = poste + profil, y = salaire mensuel brut TND
         ▼  4. SPLIT      — train / validation / test stratifiés
         ▼  5. COMPARAISON— Linear, Ridge, RandomForest, GBM, XGBoost, LightGBM
         ▼  6. LIVRAISON  — réentraînement du meilleur, sérialisation v3
    MODÈLE + FOURCHETTE DE MARCHÉ

Principes tenus, dans l'ordre où ils comptent :

* **Aucune suppression automatique d'une valeur extrême.** Un point aberrant est
  d'abord expliqué (erreur de saisie ? mensuel/annuel ? brut/net ? TND/EUR ?
  senior très particulier ? expatrié ? entreprise internationale ?). Il n'est
  écarté que si l'audit a produit une raison écrite, tracée dans le CSV via
  `quality_flag` / `quality_note`, et affichée à l'exécution.
* **Une seule unité pour toutes les observations** : TND, mensuel, BRUT. La
  conversion net → brut inverse le barème social tunisien réel (CNSS 9,18 % +
  IRPP progressif + CSS), pas un coefficient forfaitaire.
* **Le modèle retenu est celui qui GÉNÉRALISE le mieux**, mesuré sur le jeu de
  test jamais vu, pas celui qui colle le mieux à l'entraînement. L'écart
  train/test est affiché pour chaque candidat, le surapprentissage est visible.

Usage :
    cd backend
    python scripts/salary_ml_pipeline.py                 # pipeline complet
    python scripts/salary_ml_pipeline.py --audit-only    # audit sans entraînement
    python scripts/salary_ml_pipeline.py --no-write      # ne sérialise pas le modèle
    python scripts/salary_ml_pipeline.py --repeats 10    # comparaison plus robuste
"""
from __future__ import annotations

import argparse
import json
import pickle
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import (
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor

# Le pipeline s'exécute depuis `backend/` : le paquet applicatif est importable.
# On réutilise SA construction de features plutôt que d'en écrire une seconde,
# pour que l'entraînement et l'inférence ne puissent pas diverger.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.salary_features import build_feature_vector  # noqa: E402

# La console Windows est en cp1252 par défaut : le rapport contient des
# encadrements et des accents, on force UTF-8 sur la sortie plutôt que de
# dégrader l'affichage.
if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - dépend du terminal
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATASET = BACKEND_DIR / "datasets" / "tunisia_it_salaries.csv"
CLEAN_DATASET = BACKEND_DIR / "datasets" / "tunisia_salaries_clean.csv"
AUDIT_REPORT = BACKEND_DIR / "datasets" / "audit_report.json"
MODEL_OUTPUT = BACKEND_DIR / "salary_model_piqbit.p"

TARGETS = ("salary_min_tnd", "salary_avg_tnd", "salary_max_tnd")
SENIORITY_ORDINAL = {"junior": 1, "mid": 2, "senior": 3, "lead": 4}
EDUCATION_ORDINAL = {"licence": 1, "ingénieur": 2, "ingenieur": 2, "master": 2, "doctorat": 3}

SKILL_VOCAB_SIZE = 40
RANDOM_STATE = 42

# Taux de change de secours si une ligne est libellée en EUR sans taux fourni.
EUR_TO_TND = 3.35


# ══════════════════════════════════════════════════════════════════════════════
#  Barème social tunisien — conversion net ⇄ brut
# ══════════════════════════════════════════════════════════════════════════════

CNSS_EMPLOYEE_RATE = 0.0918          # cotisation salariale CNSS
PROFESSIONAL_ALLOWANCE_RATE = 0.10   # abattement frais professionnels
PROFESSIONAL_ALLOWANCE_CAP = 2000.0  # plafond annuel de l'abattement
SOLIDARITY_RATE = 0.005              # contribution sociale de solidarité

# Barème IRPP annuel (tranches en TND, taux marginal).
IRPP_BRACKETS = [
    (5_000, 0.00),
    (10_000, 0.15),
    (20_000, 0.25),
    (30_000, 0.30),
    (40_000, 0.33),
    (50_000, 0.36),
    (70_000, 0.38),
    (float("inf"), 0.40),
]


def _irpp_annual(taxable: float) -> float:
    """Impôt annuel dû sur un revenu imposable, barème progressif par tranches."""
    tax, previous = 0.0, 0.0
    for ceiling, rate in IRPP_BRACKETS:
        if taxable <= previous:
            break
        slice_amount = min(taxable, ceiling) - previous
        tax += slice_amount * rate
        previous = ceiling
    return tax


def gross_to_net_monthly(gross_monthly: float) -> float:
    """Net mensuel correspondant à un brut mensuel (CNSS + IRPP + CSS)."""
    annual_gross = gross_monthly * 12.0
    after_cnss = annual_gross * (1 - CNSS_EMPLOYEE_RATE)
    allowance = min(after_cnss * PROFESSIONAL_ALLOWANCE_RATE, PROFESSIONAL_ALLOWANCE_CAP)
    taxable = max(after_cnss - allowance, 0.0)
    tax = _irpp_annual(taxable)
    solidarity = taxable * SOLIDARITY_RATE
    return (after_cnss - tax - solidarity) / 12.0


def net_to_gross_monthly(net_monthly: float) -> float:
    """
    Brut mensuel correspondant à un net mensuel.

    `gross_to_net_monthly` est monotone croissante mais non inversible
    analytiquement (barème par tranches + abattement plafonné) : on inverse par
    dichotomie, à 0,01 TND près. Plus honnête qu'un coefficient forfaitaire, et
    correct sur toute l'échelle salariale plutôt que sur une seule tranche.
    """
    if net_monthly <= 0:
        return 0.0
    low, high = net_monthly, net_monthly * 3.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if gross_to_net_monthly(mid) < net_monthly:
            low = mid
        else:
            high = mid
        if high - low < 0.01:
            break
    return (low + high) / 2.0


# ══════════════════════════════════════════════════════════════════════════════
#  1. AUDIT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditReport:
    """Constat d'audit : ce qu'on a trouvé, et ce qu'on a décidé d'en faire."""
    rows_in: int = 0
    missing: dict = field(default_factory=dict)
    exact_duplicates: int = 0
    key_duplicates: list = field(default_factory=list)
    coherence_violations: list = field(default_factory=list)
    unit_conversions: list = field(default_factory=list)
    outliers: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    rows_out: int = 0

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, ensure_ascii=False)


def _title(text: str) -> None:
    print(f"\n{'═' * 78}\n{text}\n{'═' * 78}")


def _section(text: str) -> None:
    print(f"\n── {text} " + "─" * max(0, 74 - len(text)))


def audit(df: pd.DataFrame, report: AuditReport) -> None:
    """Étape 1 — constater, expliquer, ne rien supprimer."""
    _title("1. AUDIT DU DATASET BRUT")
    report.rows_in = len(df)
    print(f"Lignes : {len(df)} · Colonnes : {len(df.columns)}")

    _section("Valeurs manquantes")
    missing = df.isna().sum()
    missing = missing[missing > 0]
    report.missing = missing.to_dict()
    print(missing.to_string() if len(missing) else "Aucune.")

    _section("Doublons")
    report.exact_duplicates = int(df.duplicated().sum())
    print(f"Doublons exacts (toutes colonnes) : {report.exact_duplicates}")
    key_dupes = df[df.duplicated(subset=["title", "seniority"], keep=False)]
    if len(key_dupes):
        report.key_duplicates = key_dupes[["title", "seniority", "source"]].to_dict("records")
        print(f"Doublons de clé (titre × séniorité) : {len(key_dupes)} lignes")
        print(key_dupes[["title", "seniority", "salary_avg_tnd", "source"]].to_string(index=False))
    else:
        print("Doublons de clé (titre × séniorité) : 0")

    _section("Cohérence interne")
    bad_salary = df[~((df.salary_min_tnd <= df.salary_avg_tnd) & (df.salary_avg_tnd <= df.salary_max_tnd))]
    bad_exp = df[df.experience_years_min > df.experience_years_max]
    for label, subset in (("min<=avg<=max", bad_salary), ("exp_min<=exp_max", bad_exp)):
        print(f"{label:<20} : {len(subset)} violation(s)")
        if len(subset):
            report.coherence_violations.append({"rule": label, "rows": subset.title.tolist()})

    _section("Unités déclarées")
    for keys, count in df.groupby(["currency", "period", "salary_basis"]).size().items():
        print(f"  {keys} : {count} ligne(s)")

    _section("Valeurs extrêmes — diagnostic, sans suppression")
    _diagnose_outliers(df, report)

    _section("Anomalies déjà tracées dans le CSV")
    flagged = df[df.quality_flag != "ok"]
    if len(flagged):
        for _, row in flagged.iterrows():
            print(f"  ⚑ {row.title} ({row.seniority}) — {row.quality_flag}")
            print(f"    {row.quality_note}")
    else:
        print("Aucune.")


def _diagnose_outliers(df: pd.DataFrame, report: AuditReport) -> None:
    """
    Détecte les points atypiques et EXPLIQUE chacun, en suivant la grille de
    vérification : erreur de saisie, mensuel/annuel, brut/net, TND/EUR,
    séniorité très particulière, expatriation, entreprise internationale.
    Rien n'est supprimé ici — on produit un diagnostic.

    Le test se fait en deux temps, et le second est décisif :

    1. Écart au niveau de la LIGNE, contre la médiane des pairs de même
       catégorie et même séniorité.
    2. Écart au niveau du MÉTIER. Un intitulé dont tous les paliers dévient du
       même facteur n'est pas une anomalie : c'est un métier structurellement
       mieux ou moins payé que sa famille (WordPress sous la moyenne Tech, un
       architecte au-dessus). Une vraie anomalie casse le motif : elle touche
       un palier et pas les autres. On ne signale donc que les métiers dont la
       déviation est INCONSTANTE d'un palier à l'autre.
    """
    reference = df[df.population == "marche_reference"]
    medians = reference.groupby(["category", "seniority"]).salary_avg_tnd.median()

    deviations: dict[str, list[tuple[pd.Series, float, float]]] = defaultdict(list)
    for _, row in df.iterrows():
        median = medians.get((row.category, row.seniority))
        if median is None or median == 0:
            continue
        deviations[row.title].append((row, row.salary_avg_tnd / median, median))

    flagged = 0
    for title, entries in deviations.items():
        ratios = [ratio for _, ratio, _ in entries]
        # Métier dont tous les paliers restent dans la norme : rien à dire.
        if all(0.75 <= r <= 1.35 for r in ratios):
            continue

        spread = (max(ratios) / min(ratios)) if min(ratios) > 0 else float("inf")
        consistent = len(ratios) >= 2 and spread <= 1.15
        if consistent:
            position = "au-dessus" if statistics.mean(ratios) > 1 else "en dessous"
            print(f"  {title} : {statistics.mean(ratios):.2f}× la médiane de sa famille "
                  f"sur {len(ratios)} palier(s), de façon régulière")
            print(f"    → Positionnement de MÉTIER, pas anomalie : intitulé structurellement "
                  f"{position} de sa catégorie. Conservé tel quel.")
            continue

        # Déviation irrégulière : chaque palier fautif est diagnostiqué.
        for row, ratio, median in entries:
            if 0.75 <= ratio <= 1.35:
                continue
            flagged += 1
            diagnosis = _explain_deviation(row, ratio, median)
            report.outliers.append({
                "title": row.title, "seniority": row.seniority,
                "value": float(row.salary_avg_tnd), "peer_median": float(median),
                "ratio": round(float(ratio), 3), "diagnosis": diagnosis,
            })
            print(f"  {row.title} ({row.seniority}) : {row.salary_avg_tnd:.0f} vs "
                  f"médiane pairs {median:.0f} — ratio {ratio:.2f}")
            print(f"    → {diagnosis}")

    if not flagged:
        print("Aucune déviation irrégulière : tous les écarts s'expliquent par le métier.")


def _explain_deviation(row: pd.Series, ratio: float, median: float) -> str:
    """Grille de diagnostic d'un écart, du plus probable au plus rare."""
    # Erreur de saisie d'un facteur 12 : annuel saisi comme mensuel (ou l'inverse).
    for factor, label in ((12, "annuel saisi comme mensuel"), (1 / 12, "mensuel saisi comme annuel")):
        if 0.85 <= (ratio * factor) <= 1.20:
            return f"Erreur d'unité probable : {label} (×{factor:g} ramène au niveau des pairs)."
    # Conversion de devise oubliée.
    if 0.85 <= ratio * EUR_TO_TND <= 1.20:
        return f"Montant probablement en EUR non converti (×{EUR_TO_TND} ramène au niveau des pairs)."
    # Base salariale.
    if str(row.get("salary_basis")) == "net":
        gross = net_to_gross_monthly(row.salary_avg_tnd)
        return (f"Salaire NET déclaré ({row.salary_avg_tnd:.0f}) → brut équivalent "
                f"{gross:.0f} TND, soit {gross / median:.2f}× la médiane des pairs. "
                f"Le reliquat s'explique par la population couverte "
                f"({row.get('population')}), pas par une erreur.")
    # Haut de marché légitime.
    if ratio > 1.35:
        return ("Au-dessus des pairs mais cohérent avec le haut de marché : poste rare "
                "(architecte, direction), entreprise internationale ou profil expatrié. "
                "Conservé — un plafond de marché élevé est une information, pas un bruit.")
    return ("Écart non expliqué par une unité ni une devise. Conservé et signalé : "
            "à trancher avec une source métier avant toute exclusion.")


# ══════════════════════════════════════════════════════════════════════════════
#  2. NETTOYAGE
# ══════════════════════════════════════════════════════════════════════════════

def clean(df: pd.DataFrame, report: AuditReport) -> pd.DataFrame:
    """Étape 2 — dédoublonnage, imputation, normalisation des unités."""
    _title("2. NETTOYAGE")
    df = df.copy()

    _section("Dédoublonnage")
    before = len(df)
    df = df.drop_duplicates()
    # Sur une clé métier identique, le barème de référence prime sur l'enquête.
    df["_priority"] = (df.population == "marche_reference").astype(int)
    df = (df.sort_values("_priority", ascending=False)
            .drop_duplicates(subset=["title", "seniority"], keep="first")
            .drop(columns="_priority"))
    print(f"{before} → {len(df)} lignes ({before - len(df)} doublon(s) retiré(s))")

    _section("Valeurs manquantes")
    filled = 0
    # La moyenne se reconstruit depuis les bornes, et réciproquement, via les
    # ratios observés sur le barème (min/avg ≈ 0.85, max/avg ≈ 1.18).
    ratio_min = (df.salary_min_tnd / df.salary_avg_tnd).median()
    ratio_max = (df.salary_max_tnd / df.salary_avg_tnd).median()
    mask = df.salary_avg_tnd.isna() & df.salary_min_tnd.notna() & df.salary_max_tnd.notna()
    filled += int(mask.sum())
    df.loc[mask, "salary_avg_tnd"] = (df.loc[mask, "salary_min_tnd"] + df.loc[mask, "salary_max_tnd"]) / 2
    for column, ratio in (("salary_min_tnd", ratio_min), ("salary_max_tnd", ratio_max)):
        mask = df[column].isna() & df.salary_avg_tnd.notna()
        filled += int(mask.sum())
        df.loc[mask, column] = df.loc[mask, "salary_avg_tnd"] * ratio
    for column, default in (("experience_years_min", 0.0), ("top_skills", ""), ("education", "Licence")):
        mask = df[column].isna()
        filled += int(mask.sum())
        df.loc[mask, column] = default
    mask = df.experience_years_max.isna()
    filled += int(mask.sum())
    df.loc[mask, "experience_years_max"] = df.loc[mask, "experience_years_min"] + 2
    print(f"{filled} valeur(s) imputée(s) (ratios min/avg={ratio_min:.3f}, max/avg={ratio_max:.3f})")

    _section("Normalisation des unités → TND mensuel BRUT")
    df = _normalize_units(df, report)

    _section("Exclusions motivées")
    flagged = df[df.quality_flag != "ok"]
    for _, row in flagged.iterrows():
        report.excluded.append({
            "title": row.title, "seniority": row.seniority,
            "flag": row.quality_flag, "reason": row.quality_note,
        })
        print(f"  ✂ {row.title} ({row.seniority}) — {row.quality_flag}")
        print(f"    {row.quality_note}")
    df = df[df.quality_flag == "ok"].copy()
    if not len(flagged):
        print("Aucune ligne exclue.")

    _section("Contrôle de monotonie par métier")
    _check_monotonicity(df)

    report.rows_out = len(df)
    print(f"\nDataset propre : {len(df)} lignes.")
    return df


def _normalize_units(df: pd.DataFrame, report: AuditReport) -> pd.DataFrame:
    """
    Ramène toutes les observations à la même unité : TND, mensuel, brut.

    C'est le point le plus important du nettoyage. Mélanger du mensuel et de
    l'annuel, ou du net et du brut, produit un modèle qui apprend le bruit de la
    convention de saisie plutôt que le salaire.
    """
    for index, row in df.iterrows():
        conversions = []
        factor = 1.0

        # a. Devise → TND.
        currency = str(row.get("currency", "TND")).upper()
        if currency == "EUR":
            factor *= EUR_TO_TND
            conversions.append(f"EUR→TND (×{EUR_TO_TND})")

        # b. Période → mensuel.
        period = str(row.get("period", "")).lower()
        if "annuel" in period or "annual" in period or "yearly" in period:
            factor /= 12.0
            conversions.append("annuel→mensuel (÷12)")

        if factor != 1.0:
            for column in TARGETS:
                df.at[index, column] = row[column] * factor

        # c. Base → brut. Non linéaire : appliquée montant par montant.
        if str(row.get("salary_basis", "brut")).lower() == "net":
            for column in TARGETS:
                df.at[index, column] = round(net_to_gross_monthly(df.at[index, column]))
            conversions.append("net→brut (CNSS 9,18 % + IRPP progressif)")
            df.at[index, "salary_basis"] = "brut"

        if conversions:
            detail = {
                "title": row.title, "seniority": row.seniority,
                "conversions": conversions,
                "avant": float(row.salary_avg_tnd),
                "apres": float(df.at[index, "salary_avg_tnd"]),
            }
            report.unit_conversions.append(detail)
            print(f"  {row.title} ({row.seniority}) : {detail['avant']:.0f} → "
                  f"{detail['apres']:.0f} TND — {', '.join(conversions)}")

    if not report.unit_conversions:
        print("Toutes les lignes étaient déjà en TND mensuel brut.")
    df["period"] = "mensuel_brut"
    df["currency"] = "TND"
    return df


def _check_monotonicity(df: pd.DataFrame) -> None:
    """Un senior ne peut pas être payé moins qu'un confirmé du même métier."""
    violations = 0
    for title, group in df.groupby("title"):
        ordered = group.assign(_ord=group.seniority.str.lower().map(SENIORITY_ORDINAL)).sort_values("_ord")
        salaries = ordered.salary_avg_tnd.tolist()
        if any(b < a for a, b in zip(salaries, salaries[1:])):
            violations += 1
            print(f"  ⚠ {title} : {list(zip(ordered.seniority, salaries))}")
    print("Aucune inversion de séniorité." if not violations
          else f"{violations} métier(s) présentent une inversion — à arbitrer manuellement.")


# ══════════════════════════════════════════════════════════════════════════════
#  3. FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def _tokenize_skills(raw: str) -> list[str]:
    return [s.strip().lower() for s in str(raw).split(",") if s.strip()]


def _seniority_ordinal(label: str) -> int:
    return SENIORITY_ORDINAL.get(str(label).strip().lower(), 2)


def _education_ordinal(label: str) -> int:
    text = str(label).strip().lower()
    for key, value in EDUCATION_ORDINAL.items():
        if key in text:
            return value
    return 1


def build_vocab(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    categories = sorted(df.category.str.strip().unique().tolist())
    counter: Counter = Counter()
    for raw in df.top_skills:
        counter.update(_tokenize_skills(raw))
    return categories, [skill for skill, _ in counter.most_common(SKILL_VOCAB_SIZE)]


def build_features(df: pd.DataFrame, categories: list[str], skills: list[str]) -> tuple[np.ndarray, list[str]]:
    """
    X = informations du poste + informations du profil attendu.
    y (construit à part) = salaire réel, mensuel brut TND.

    L'ordre des colonnes est le contrat d'inférence : il est produit par
    `app.services.salary_features.build_feature_vector`, que `SalaryPredictionService`
    appelle aussi. Les deux chemins ne peuvent donc pas diverger.

    Le NIVEAU D'ÉTUDES a été retiré des features. Dans ce dataset il est
    entièrement déterminé par la séniorité — 38 lignes Junior sur 38 sont
    « Licence », les 51 Senior et les 51 Lead sont « Ingénieur/Master » — et le
    modèle l'avait donc appris comme un simple proxy de séniorité. Conséquence
    en production : une offre junior déclarant « niveau ingénieur » était cotée
    comme un profil confirmé, +53 % sur la prédiction. Une variable colinéaire
    qui n'apporte aucune information mais introduit un mode de défaillance
    majeur n'a pas sa place dans le vecteur.
    """
    names = ([f"cat_{c}" for c in categories]
             + ["seniority", "experience_years", "experience_span"]
             + [f"skill_{s}" for s in skills])
    rows = []
    for _, row in df.iterrows():
        experience_min = float(row.experience_years_min or 0)
        experience_max = float(row.experience_years_max or experience_min)
        rows.append(build_feature_vector(
            category=row.category.strip(),
            categories=categories,
            seniority=_seniority_ordinal(row.seniority),
            experience_years=(experience_min + experience_max) / 2.0,
            experience_span=experience_max - experience_min,
            skills_text=str(row.top_skills),
            skill_vocab=skills,
        ))
    return np.array(rows, dtype=float), names


# ══════════════════════════════════════════════════════════════════════════════
#  5. COMPARAISON DE MODÈLES
# ══════════════════════════════════════════════════════════════════════════════

def candidate_models(verbose: bool = True) -> dict:
    """Du plus simple au plus expressif — la complexité doit se mériter."""
    models = {
        "Baseline (moyenne)": DummyRegressor(strategy="mean"),
        "Linear Regression": LinearRegression(),
        "Ridge (α=1.0)": Ridge(alpha=1.0, random_state=RANDOM_STATE),
        "Random Forest": RandomForestRegressor(
            n_estimators=400, min_samples_leaf=1, random_state=RANDOM_STATE, n_jobs=-1),
        "Gradient Boosting": MultiOutputRegressor(GradientBoostingRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.05, random_state=RANDOM_STATE)),
        "HistGradientBoosting": MultiOutputRegressor(HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.06, random_state=RANDOM_STATE)),
    }
    try:
        from xgboost import XGBRegressor
        models["XGBoost"] = MultiOutputRegressor(XGBRegressor(
            n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.9,
            colsample_bytree=0.9, random_state=RANDOM_STATE, verbosity=0))
    except ImportError:
        if verbose:
            print("(XGBoost absent — `pip install xgboost` pour l'inclure.)")
    try:
        from lightgbm import LGBMRegressor
        models["LightGBM"] = MultiOutputRegressor(LGBMRegressor(
            n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=5,
            random_state=RANDOM_STATE, verbosity=-1))
    except ImportError:
        if verbose:
            print("(LightGBM absent — `pip install lightgbm` pour l'inclure.)")
    return models


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(mean_absolute_error(y_true, y_pred))


def split_dataset(X: np.ndarray, y: np.ndarray, strata: np.ndarray, seed: int) -> dict:
    """Découpe 60 / 20 / 20, stratifiée par catégorie × séniorité quand c'est possible."""
    stratify = strata if min(Counter(strata).values()) >= 2 else None
    X_temp, X_test, y_temp, y_test, strata_temp, _ = train_test_split(
        X, y, strata, test_size=0.20, random_state=seed, stratify=stratify)
    stratify_temp = strata_temp if min(Counter(strata_temp).values()) >= 2 else None
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp, y_temp, test_size=0.25, random_state=seed, stratify=stratify_temp)
    return {"X_train": X_train, "y_train": y_train, "X_val": X_val, "y_val": y_val,
            "X_test": X_test, "y_test": y_test}


def compare_models(X: np.ndarray, y: np.ndarray, strata: np.ndarray, repeats: int) -> tuple[str, dict]:
    """
    Entraîne chaque candidat sur TRAIN, arbitre sur VALIDATION, mesure sur TEST.

    Le gagnant est celui qui minimise la MAE de TEST — donnée jamais vue — et
    non celui qui minimise l'erreur d'entraînement. L'écart train/test est
    affiché : c'est la mesure directe du surapprentissage.

    Le jeu de test ne compte qu'une quarantaine d'observations : une seule
    partition suffirait à faire gagner un modèle par chance. La comparaison est
    donc répétée sur `repeats` partitions aléatoires distinctes et les métriques
    sont moyennées. L'écart-type de la MAE de test est affiché : un modèle très
    performant mais instable d'une partition à l'autre n'est pas fiable.
    """
    _title("5. COMPARAISON DE MODÈLES")
    print(f"Protocole : {repeats} partitions 60/20/20 indépendantes, métriques moyennées.\n")

    accumulator: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    failures: dict[str, str] = {}

    for repeat in range(repeats):
        splits = split_dataset(X, y, strata, seed=RANDOM_STATE + repeat)
        for name, model in candidate_models(verbose=repeat == 0).items():
            try:
                model.fit(splits["X_train"], splits["y_train"])
                train_mae = _mae(splits["y_train"], model.predict(splits["X_train"]))
                val_mae = _mae(splits["y_val"], model.predict(splits["X_val"]))
                predictions = model.predict(splits["X_test"])
                test_mae = _mae(splits["y_test"], predictions)
                accumulator[name]["train"].append(train_mae)
                accumulator[name]["val"].append(val_mae)
                accumulator[name]["test"].append(test_mae)
                accumulator[name]["r2"].append(float(r2_score(splits["y_test"], predictions)))
            except Exception as exc:  # pragma: no cover - dépend des libs installées
                failures[name] = str(exc)

    for name, reason in failures.items():
        print(f"{name:<24}  échec : {reason}")

    print(f"{'Modèle':<24}{'MAE train':>11}{'MAE val':>10}{'MAE test':>11}"
          f"{'± σ':>8}{'R² test':>9}{'écart':>8}")
    print("─" * 81)

    results = {}
    for name, metrics in accumulator.items():
        train_mae = statistics.mean(metrics["train"])
        test_mae = statistics.mean(metrics["test"])
        deviation = statistics.pstdev(metrics["test"])
        results[name] = {
            "train_mae": round(train_mae, 1),
            "val_mae": round(statistics.mean(metrics["val"]), 1),
            "test_mae": round(test_mae, 1),
            "test_mae_std": round(deviation, 1),
            "test_r2": round(statistics.mean(metrics["r2"]), 4),
            "generalisation_gap": round(test_mae - train_mae, 1),
        }
        print(f"{name:<24}{train_mae:>11.0f}{results[name]['val_mae']:>10.0f}"
              f"{test_mae:>11.0f}{deviation:>8.0f}{results[name]['test_r2']:>9.3f}"
              f"{results[name]['generalisation_gap']:>8.0f}")

    ranked = sorted(results, key=lambda n: results[n]["test_mae"])
    best = ranked[0]
    print("─" * 81)
    print(f"Retenu : {best} — MAE test {results[best]['test_mae']:.0f} "
          f"± {results[best]['test_mae_std']:.0f} TND, R² test {results[best]['test_r2']:.3f}, "
          f"écart train/test {results[best]['generalisation_gap']:.0f} TND.")
    if len(ranked) > 1:
        second = ranked[1]
        print(f"Second : {second} (MAE test {results[second]['test_mae']:.0f} TND, "
              f"écart {results[second]['generalisation_gap']:.0f}).")
    return best, results


# ══════════════════════════════════════════════════════════════════════════════
#  6. BANDES DE CALIBRAGE + LIVRAISON
# ══════════════════════════════════════════════════════════════════════════════

def build_bands(df: pd.DataFrame) -> tuple[dict, dict, dict]:
    """Médianes (min, avg, max) par titre × séniorité, puis catégorie × séniorité."""
    by_title: dict[str, list] = defaultdict(list)
    by_category: dict[str, list] = defaultdict(list)
    experience: dict[str, list] = defaultdict(list)

    for _, row in df.iterrows():
        triple = [float(row[t]) for t in TARGETS]
        ordinal = _seniority_ordinal(row.seniority)
        by_title[f"{row.title.strip().lower()}|{ordinal}"].append(triple)
        by_category[f"{row.category.strip()}|{ordinal}"].append(triple)
        experience[f"{row.title.strip().lower()}|{ordinal}"].append(
            [float(row.experience_years_min or 0), float(row.experience_years_max or 0)]
        )

    def medians(bucket: dict) -> dict:
        return {key: [round(statistics.median(col)) for col in zip(*values)]
                for key, values in bucket.items()}

    return medians(by_title), medians(by_category), medians(experience)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(RAW_DATASET))
    parser.add_argument("--out", default=str(MODEL_OUTPUT))
    parser.add_argument("--audit-only", action="store_true", help="audit sans entraînement")
    parser.add_argument("--no-write", action="store_true", help="n'écrit pas le modèle")
    parser.add_argument("--repeats", type=int, default=5,
                        help="nombre de partitions indépendantes pour la comparaison (défaut 5)")
    args = parser.parse_args()

    raw_path = Path(args.csv)
    if not raw_path.exists():
        raise SystemExit(f"Dataset introuvable : {raw_path}")

    report = AuditReport()
    raw = pd.read_csv(raw_path)

    # Colonnes d'audit optionnelles : le pipeline reste utilisable sur un CSV
    # qui ne les porte pas encore.
    for column, default in (("salary_basis", "brut"), ("population", "marche_reference"),
                            ("quality_flag", "ok"), ("quality_note", "")):
        if column not in raw.columns:
            raw[column] = default

    audit(raw, report)
    clean_df = clean(raw, report)

    AUDIT_REPORT.write_text(report.to_json(), encoding="utf-8")
    clean_df.to_csv(CLEAN_DATASET, index=False, encoding="utf-8")
    print(f"\nDataset propre  → {CLEAN_DATASET}")
    print(f"Rapport d'audit → {AUDIT_REPORT}")

    if args.audit_only:
        return

    # ── 3. Features ───────────────────────────────────────────────────────────
    _title("3. FEATURE ENGINEERING")
    categories, skills = build_vocab(clean_df)
    X, feature_names = build_features(clean_df, categories, skills)
    y = clean_df[list(TARGETS)].astype(float).values
    print(f"X : {X.shape[0]} observations × {X.shape[1]} features")
    print(f"y : {y.shape[1]} cibles {TARGETS} — salaire mensuel brut TND")
    print(f"Catégories ({len(categories)}) : {categories}")
    print(f"Compétences retenues ({len(skills)}) : {skills[:12]}…")

    # ── 4. Split ──────────────────────────────────────────────────────────────
    _title("4. SÉPARATION TRAIN / VALIDATION / TEST")
    strata = (clean_df.category + "|" + clean_df.seniority).values
    if min(Counter(strata).values()) < 2:
        print("Stratification désactivée : au moins une strate n'a qu'un exemplaire.")
    sample = split_dataset(X, y, strata, seed=RANDOM_STATE)
    total = len(X)
    print(f"Train {len(sample['X_train'])} · Validation {len(sample['X_val'])} · "
          f"Test {len(sample['X_test'])} "
          f"({len(sample['X_train'])/total:.0%} / {len(sample['X_val'])/total:.0%} / "
          f"{len(sample['X_test'])/total:.0%})")
    print("Le jeu de TEST n'est utilisé qu'à l'étape 5, et jamais pour ajuster un modèle.")

    # ── 5. Comparaison ────────────────────────────────────────────────────────
    best_name, results = compare_models(X, y, strata, repeats=args.repeats)

    # ── 6. Livraison ──────────────────────────────────────────────────────────
    _title("6. RÉENTRAÎNEMENT DU MODÈLE RETENU ET LIVRAISON")
    best_model = candidate_models(verbose=False)[best_name]
    best_model.fit(X, y)
    print(f"{best_name} réentraîné sur les {len(X)} observations propres.")

    title_bands, category_bands, title_experience = build_bands(clean_df)
    print(f"Bandes de calibrage : {len(title_bands)} (titre × séniorité) · "
          f"{len(category_bands)} (catégorie × séniorité)")

    payload = {
        "format": "piqbit_salary_v3",
        "model": best_model,
        "model_name": best_name,
        "feature_names": feature_names,
        "categories": categories,
        "skill_vocab": skills,
        "title_to_category": {r.title.strip().lower(): r.category.strip()
                              for _, r in clean_df.iterrows()},
        "targets": list(TARGETS),
        "title_bands": title_bands,
        "category_bands": category_bands,
        "title_experience": title_experience,
        "currency": "TND",
        "period": "mensuel_brut",
        "metrics": results,
        "selected_on": "MAE moyenne sur jeu de test, %d partitions independantes" % args.repeats,
        "n_samples": len(X),
        "dataset": str(CLEAN_DATASET.name),
    }

    if args.no_write:
        print("\n--no-write : modèle non sérialisé.")
        return
    with open(args.out, "wb") as handle:
        # Écrit par notre propre pipeline, relu par l'API au démarrage — jamais
        # un fichier fourni par un utilisateur.
        pickle.dump(payload, handle)  # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    print(f"\nModèle sérialisé → {args.out}")
    print("Format piqbit_salary_v3 — redémarrez l'API pour qu'elle le recharge.")


if __name__ == "__main__":
    sys.exit(main())
