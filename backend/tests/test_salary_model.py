"""
Tests du modèle ML de prédiction de salaire entraîné sur
`datasets/tunisia_it_salaries.csv` (script scripts/salary_ml_pipeline.py).

On valide :
  - la construction des features (longueur cohérente avec l'inférence)
  - le contrat d'entraînement -> sérialisation piqbit_salary_vN
  - que le service charge le modèle et prédit un salaire réaliste (chemin ML,
    pas le fallback heuristique)
  - que la réponse déclare le modèle d'après l'artefact chargé (model_type,
    model_version), et non d'après un libellé écrit en dur

Ces tests sont purs (pas de DB) et s'exécutent hors event-loop.
"""
import importlib.util
import pickle
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PIPELINE = BACKEND_DIR / "scripts" / "salary_ml_pipeline.py"
MODEL_FILE = BACKEND_DIR / "salary_model_piqbit.p"

sklearn = pytest.importorskip("sklearn")
pd = pytest.importorskip("pandas")


def _load_pipeline():
    """
    Charge scripts/salary_ml_pipeline.py comme module.

    Le module est inscrit dans sys.modules AVANT d'être exécuté : il déclare une
    `@dataclass`, et ce décorateur relit sys.modules[module] pendant
    l'exécution. Sans l'inscription, le chargement lève une AttributeError.
    """
    spec = importlib.util.spec_from_file_location("salary_ml_pipeline", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_features_length_matches_vocab():
    pipeline = _load_pipeline()
    df = pd.read_csv(pipeline.CLEAN_DATASET)
    categories, skill_vocab = pipeline.build_vocab(df)

    X, names = pipeline.build_features(df, categories, skill_vocab)
    # one-hot(catégories) + séniorité + expérience + amplitude + multi-hot(compétences)
    assert X.shape[1] == len(names) == len(categories) + 3 + len(skill_vocab)


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_pipeline_and_artefact_share_the_feature_vector():
    """
    Contrat entraînement / production : le pipeline produit exactement les
    colonnes, dans le même ordre, que celles enregistrées dans l'artefact servi.
    Échoue si le jeu de données change sans réentraînement, ou si un autre
    script réécrit l'artefact.
    """
    pipeline = _load_pipeline()
    df = pd.read_csv(pipeline.CLEAN_DATASET)
    categories, skill_vocab = pipeline.build_vocab(df)
    _, names = pipeline.build_features(df, categories, skill_vocab)

    with open(MODEL_FILE, "rb") as handle:
        artefact = pickle.load(handle)
    assert names == artefact["feature_names"]


def test_seniority_ordinal_scale():
    pipeline = _load_pipeline()
    assert pipeline._seniority_ordinal("Junior") == 1
    assert pipeline._seniority_ordinal("Mid") == 2
    assert pipeline._seniority_ordinal("Senior") == 3
    assert pipeline._seniority_ordinal("Lead") == 4
    # Valeur inconnue -> mid (2), comme _guess_seniority côté inférence.
    assert pipeline._seniority_ordinal("???") == 2


def test_dataset_present_and_nonempty():
    pipeline = _load_pipeline()
    df = pd.read_csv(pipeline.RAW_DATASET)
    assert len(df) > 100
    assert (df["salary_avg_tnd"] > 0).all()


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné (lancer scripts/salary_ml_pipeline.py)")
def test_service_loads_trained_model():
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService()
    assert svc.piqbit is not None, "un modèle PIQBIT (format piqbit_salary_vN) doit être chargé"
    assert svc.heuristic is False


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_predict_returns_realistic_tnd_salary():
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService()
    result = svc.predict_salary({
        "title": "Senior Data Scientist",
        "skills_text": "python sql machine learning",
        "experience_years": 6,
    })
    # Le modèle se déclare d'après l'artefact, jamais d'après un libellé figé :
    # cette assertion reste vraie si un réentraînement retient un autre gagnant.
    assert result["model_type"].startswith("ml_")
    assert result["model_type"] == svc.model_type
    assert result["model_version"] == svc.piqbit["format"]
    assert result["currency"] == "TND"
    # Salaire mensuel tunisien plausible pour un senior data scientist.
    assert 1500 <= result["predicted_salary"] <= 10000
    assert result["range_min"] < result["predicted_salary"] < result["range_max"]


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_seniority_increases_salary():
    """Un profil senior doit être prédit au-dessus d'un profil junior équivalent."""
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService()
    junior = svc.predict_salary({"title": "Junior Backend Developer", "skills_text": "python sql"})
    senior = svc.predict_salary({"title": "Senior Backend Developer", "skills_text": "python sql"})
    assert senior["predicted_salary"] >= junior["predicted_salary"]


# ── Identité du modèle : lue dans l'artefact, jamais écrite en dur ────────────

def test_identifiant_derive_du_nom_d_algorithme():
    from app.services.salary_prediction_service import _identifiant
    assert _identifiant("Gradient Boosting") == "gradient_boosting"
    assert _identifiant("Random Forest") == "random_forest"
    # Lettre grecque et ponctuation : rien de non-ASCII ne passe dans l'identifiant.
    assert _identifiant("Ridge (α=1.0)") == "ridge_1_0"
    assert _identifiant("XGBoost") == "xgboost"


def test_model_type_suit_l_artefact_charge():
    """Sans dépendre d'un fichier : on pose l'artefact à la main."""
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService.__new__(SalaryPredictionService)

    # Artefact v3 : le nom du gagnant est inscrit, il fait foi.
    svc.piqbit = {"format": "piqbit_salary_v3", "model_name": "Gradient Boosting"}
    assert svc.model_type == "ml_gradient_boosting"
    assert svc.model_version == "piqbit_salary_v3"

    # Artefact v2 (ancien script train_salary_model.py, retiré) : pas de
    # model_name, c'était une forêt aléatoire — et l'API renvoie la même valeur
    # qu'avant le correctif.
    svc.piqbit = {"format": "piqbit_salary_v2"}
    assert svc.model_type == "ml_random_forest"

    # Aucun modèle PIQBIT : le service se déclare heuristique.
    svc.piqbit = None
    assert svc.model_type == "heuristic"
    assert svc.model_version is None


# ── Corrections V1.2 : features riches réellement prises en compte ────────────

def test_seniority_from_experience_thresholds():
    from app.services.salary_prediction_service import SalaryPredictionService as S
    assert S._seniority_from_experience(1) == 1
    assert S._seniority_from_experience(3) == 2
    assert S._seniority_from_experience(6) == 3
    assert S._seniority_from_experience(12) == 4
    assert S._seniority_from_experience(None) is None


def test_resolve_seniority_priority():
    from app.services.salary_prediction_service import SalaryPredictionService as S
    # Explicite > titre > expérience.
    assert S._resolve_seniority("Developer", 2, "lead") == 4
    # Titre prime sur l'expérience.
    assert S._resolve_seniority("Senior Developer", 1, None) == 3
    # Sans signal de titre : déduit de l'expérience.
    assert S._resolve_seniority("Frontend Developer", 10, None) == 4
    assert S._resolve_seniority("Frontend Developer", 1, None) == 1
    # Aucun signal : défaut Mid.
    assert S._resolve_seniority("Frontend Developer", None, None) == 2


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_experience_drives_prediction_without_title_keyword():
    """Correctif clé : l'expérience influence la prédiction même si le titre
    ne contient aucun mot de séniorité (avant le fix, elle était ignorée)."""
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService()
    base = {"title": "Backend Developer", "skills_text": "php sql", "description": "x"}
    junior = svc.predict_salary({**base, "experience_years": 1})["predicted_salary"]
    senior = svc.predict_salary({**base, "experience_years": 10})["predicted_salary"]
    assert senior > junior * 1.2


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_confidence_increases_with_rich_features():
    from app.services.salary_prediction_service import SalaryPredictionService

    svc = SalaryPredictionService()
    poor = svc.predict_salary({"title": "Developer"})["confidence"]
    rich = svc.predict_salary({
        "title": "Senior Developer",
        "skills_text": "python aws",
        "experience_years": 6,
        "description": "poste backend",
    })["confidence"]
    assert rich > poor


def test_jobdatarequest_schema_carries_rich_features():
    """Non-régression du bug principal : le schéma ne doit PLUS dropper
    skills_text / experience_years / seniority (sinon le modèle les perd)."""
    from app.api.v1.endpoints.negotiations import JobDataRequest

    payload = JobDataRequest(
        job_id="j1", title="Frontend Developer",
        skills_text="react, angular, typescript",
        experience_years=5, seniority="senior",
    )
    dumped = payload.model_dump()
    assert dumped["skills_text"] == "react, angular, typescript"
    assert dumped["experience_years"] == 5
    assert dumped["seniority"] == "senior"
