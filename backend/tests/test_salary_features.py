"""
Tests du contrat de features salariales (`app/services/salary_features.py`) et
des trois défauts d'inférence qu'il corrige.

Le cas de référence est celui remonté en production :

    offre    : « Développeur(se) Full Stack Junior – Node.js / React.js »
    profil   : 1 an d'expérience, niveau ingénieur
    barème   : Full Stack Developer / Junior = 1350 / 1600 / 1900 TND
    modèle   : annonçait 1750 – 2150 TND avec 90 % de confiance

Trois causes, indépendantes, toutes verrouillées ici :

1. `"java" in "javascript"` est vrai en Python : la détection des compétences
   par sous-chaîne attribuait Java à une offre React/Node.
2. Le barème est en anglais, les offres en français : la recherche par titre
   échouait toujours et retombait sur la bande générique de la catégorie.
3. Le niveau d'études, colinéaire avec la séniorité dans le dataset, avait été
   appris comme un proxy de séniorité : déclarer « ingénieur » sur une offre
   junior la faisait coter comme un profil confirmé.

Tests purs : ni base de données, ni event-loop.
"""
from pathlib import Path

import pytest

from app.services.salary_features import (
    build_feature_vector,
    canonical_title,
    normalize_text,
    skill_hits,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_FILE = BACKEND_DIR / "salary_model_piqbit.p"

# Bande du barème pour le cas de référence.
FULLSTACK_JUNIOR = (1350, 1600, 1900)


# ── 1. Détection des compétences ──────────────────────────────────────────────

def test_java_nest_pas_detecte_dans_javascript():
    """Le bug d'origine : une offre React/Node se voyait attribuer Java."""
    vocab = ["java", "javascript", "react", "node"]
    trouves = [v for v, b in zip(vocab, skill_hits("JavaScript, Node.js, React", vocab)) if b]
    assert "java" not in trouves
    assert {"javascript", "react", "node"} <= set(trouves)


def test_java_reste_detecte_quand_il_est_vraiment_present():
    vocab = ["java", "javascript", "spring"]
    trouves = [v for v, b in zip(vocab, skill_hits("Java, Spring Boot", vocab)) if b]
    assert "java" in trouves
    assert "javascript" not in trouves


def test_les_competences_pointees_restent_detectees():
    """« node.js » doit déclencher « node », « react.js » déclencher « react »."""
    vocab = ["node", "react", "sql"]
    assert skill_hits("Node.js / React.js", vocab) == [1, 1, 0]


def test_detection_insensible_aux_accents_et_a_la_casse():
    vocab = ["sécurité", "négociation"]
    assert skill_hits("SECURITE, Negociation", vocab) == [1, 1]


def test_competences_multi_mots():
    vocab = ["machine learning", "power bi"]
    assert skill_hits("Machine Learning, Power BI", vocab) == [1, 1]


def test_aucune_competence_donne_un_vecteur_nul():
    assert skill_hits("", ["java", "react"]) == [0, 0]


# ── 2. Normalisation des intitulés ────────────────────────────────────────────

TITRES_CONNUS = [
    "full stack developer", "backend developer", "frontend developer",
    "mobile developer", ".net developer", "devops engineer", "data scientist",
    "project manager", "it recruiter", "accountant", "qa engineer",
]


@pytest.mark.parametrize("intitule,attendu", [
    ("Développeur(se) Full Stack Junior – Node.js / React.js", "full stack developer"),
    ("Développeur Fullstack Angular / Spring Boot", "full stack developer"),
    ("Développeur(se) Backend Java (H/F)", "backend developer"),
    ("Développeur Frontend React", "frontend developer"),
    ("Ingénieur DevOps Senior", "devops engineer"),
    ("Développeur Mobile (H/F)", "mobile developer"),
    ("Chef de projet technique", "project manager"),
    ("Recruteur IT", "it recruiter"),
    ("Data Scientist confirmé", "data scientist"),
    ("Comptable", "accountant"),
    ("Full Stack Developer", "full stack developer"),
])
def test_un_intitule_francais_retrouve_son_titre_de_bareme(intitule, attendu):
    assert canonical_title(intitule, TITRES_CONNUS) == attendu


def test_un_intitule_inconnu_ne_force_pas_une_correspondance():
    """Mieux vaut retomber sur la catégorie qu'apparier n'importe quoi."""
    assert canonical_title("Astronaute sénior", TITRES_CONNUS) is None
    assert canonical_title("", TITRES_CONNUS) is None


def test_la_marque_de_genre_ne_tronque_pas_le_titre():
    """« Développeur(se) Full Stack » ne doit pas se réduire à « Développeur »,
    qui recouvre autant « .net developer » que « full stack developer »."""
    assert canonical_title("Développeur(se) Full Stack", TITRES_CONNUS) == "full stack developer"


def test_normalisation_du_texte():
    assert normalize_text("Développeur(se) — Node.js / React") == "developpeur se node.js react"


# ── 3. Le vecteur de features ─────────────────────────────────────────────────

def test_le_vecteur_ne_contient_plus_le_niveau_detudes():
    """3 features centrales — séniorité, expérience, amplitude — et rien d'autre."""
    vec = build_feature_vector(
        category="Tech", categories=["Data", "Tech"], seniority=1,
        experience_years=1.0, experience_span=2.0,
        skills_text="react, node", skill_vocab=["react", "node", "java"],
    )
    assert len(vec) == 2 + 3 + 3
    assert vec[:2] == [0.0, 1.0]            # one-hot catégorie
    assert vec[2:5] == [1.0, 1.0, 2.0]      # séniorité, expérience, amplitude
    assert vec[5:] == [1.0, 1.0, 0.0]       # react, node, PAS java


def test_le_vecteur_est_identique_a_celui_de_lentrainement():
    """Le pipeline et le service doivent produire le même vecteur."""
    import importlib.util
    import sys

    chemin = BACKEND_DIR / "scripts" / "salary_ml_pipeline.py"
    spec = importlib.util.spec_from_file_location("salary_ml_pipeline", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # Le pipeline appelle la même fonction : le contrat tient par construction.
    assert module.build_feature_vector is build_feature_vector


# ── 4. Le cas de référence, de bout en bout ───────────────────────────────────

@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_offre_junior_reelle_predit_la_bande_du_bareme():
    from app.services.salary_prediction_service import SalaryPredictionService

    band = SalaryPredictionService().market_band({
        "title": "Développeur(se) Full Stack Junior – Node.js / React.js",
        "skills_text": "JavaScript, Node.js, React, Git",
        "experience_years": 1,
        "description": "Profil junior, jeune diplômé accepté.",
        "education": "Ingénieur",
    })
    bas, point, haut = FULLSTACK_JUNIOR
    assert band["seniority_label"] == "Junior"
    assert band["min"] == pytest.approx(bas, abs=100)
    assert band["max"] == pytest.approx(haut, abs=100)
    assert band["avg"] == pytest.approx(point, abs=150)


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_le_niveau_detudes_ninfluence_plus_la_prediction():
    """Régression clé : « ingénieur » sur une offre junior gonflait de 53 %."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    base = {
        "title": "Développeur Full Stack Junior",
        "skills_text": "JavaScript, React, Node",
        "experience_years": 1,
    }
    sans = service.market_band(base)
    avec = service.market_band({**base, "education": "Ingénieur/Master"})
    doctorat = service.market_band({**base, "education": "Doctorat"})
    assert sans["min"] == avec["min"] == doctorat["min"]
    assert sans["max"] == avec["max"] == doctorat["max"]


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_un_junior_est_cote_sous_un_confirme_du_meme_metier():
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    junior = service.market_band({"title": "Développeur Full Stack Junior",
                                  "skills_text": "react, node", "experience_years": 1})
    confirme = service.market_band({"title": "Développeur Full Stack",
                                    "skills_text": "react, node", "experience_years": 3})
    assert junior["max"] < confirme["max"]


# ── 5. La confiance annoncée ──────────────────────────────────────────────────

@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_la_confiance_ne_depasse_jamais_75_pourcent():
    """Le barème n'est qu'une estimation de marché : 90 % était intenable."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    riche = service.predict_salary({
        "title": "Développeur Full Stack Junior", "skills_text": "react, node, sql",
        "experience_years": 1, "description": "x" * 800,
    })
    assert riche["confidence"] <= 0.75


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_la_confiance_baisse_quand_la_source_est_moins_sure():
    """Titre reconnu > famille de métier > extrapolation."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    connu = service.predict_salary({
        "title": "Développeur Full Stack Junior", "skills_text": "react",
        "experience_years": 1, "description": "x" * 400,
    })["confidence"]
    inconnu = service.predict_salary({
        "title": "Poste totalement exotique", "skills_text": "",
        "experience_years": None, "description": "",
    })["confidence"]
    assert connu > inconnu
