"""
Tests du moteur de décision de négociation salariale
(`app/services/negotiation_analysis_service.py`) et de la fourchette de marché
produite par `SalaryPredictionService`.

Le cas de référence est celui remonté en production :

    offre        : Full Stack Developer, 2 ans requis, budget 1 400 – 1 700 TND
    candidat     : 5,9 ans d'expérience, matching 88/100
    demande      : 1 700 TND  (= exactement le maximum annoncé)

L'ancien moteur répondait « dépasse le budget de base (1 400 TND) de plus de
15 % » et « écart demande / marché = −2 400 » : il comparait la demande au
MINIMUM du budget, et le marché à un point unique. Les tests ci-dessous
verrouillent la lecture correcte.

Les tests du moteur sont purs (ni base ni event-loop) ; deux tests
d'intégration en fin de fichier rejouent le cas complet via l'API.
"""
from pathlib import Path

import pytest

from app.services.negotiation_analysis_service import (
    NegotiationAnalysisService,
    negotiation_analysis_service,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_FILE = BACKEND_DIR / "salary_model_piqbit.p"

# Bornes du cas de référence.
BUDGET_MIN, BUDGET_MAX = 1400.0, 1700.0
MARKET_MIN, MARKET_MAX, MARKET_REF = 2150.0, 3600.0, 3000.0


def _analyze(**overrides):
    """Cas de référence, surchargeable champ par champ."""
    params = dict(
        candidate_name="Candidat Test",
        budget_min=BUDGET_MIN,
        budget_max=BUDGET_MAX,
        requested_salary=1700.0,
        market_min=MARKET_MIN,
        market_max=MARKET_MAX,
        market_reference=MARKET_REF,
        candidate_experience_years=5.9,
        required_experience_years=2.0,
        match_score=88.0,
        seniority_label="Confirmé",
    )
    params.update(overrides)
    return negotiation_analysis_service.analyze(**params)


# ── Le bug principal : demande == maximum annoncé ─────────────────────────────

def test_demande_au_maximum_du_budget_ne_depasse_rien():
    """1 700 demandés sur une fourchette 1 400–1 700 : dépassement = 0 TND."""
    result = _analyze()
    assert result["budget_overrun"] == 0.0
    assert result["position_in_range"] == 100.0
    assert result["verdict"] == "acceptable"
    assert result["recommended_salary"] == 1700.0
    assert "top_of_range" in result["signals"]


def test_aucun_avertissement_de_depassement_budgetaire():
    """L'explication ne doit contenir aucune alerte de dépassement."""
    result = _analyze()
    assert "dépassement du budget = 0 TND" in result["explanation"]
    assert "dépasse le budget" not in result["explanation"]
    assert "⚠️" not in result["explanation"]


def test_ecart_marche_nul_quand_la_demande_est_dans_la_fourchette():
    """Le marché est une fourchette : pas d'« écart » tant qu'on est dedans."""
    result = _analyze(requested_salary=2500.0)
    assert result["market_gap"] == 0.0
    assert "above_market" not in result["signals"]
    assert "below_market" not in result["signals"]


def test_demande_sous_le_marche_signale_un_candidat_sous_paye():
    """1 700 < plancher marché 2 150 : le candidat est potentiellement sous-payé."""
    result = _analyze()
    assert "below_market" in result["signals"]
    assert result["market_gap"] == 1700.0 - MARKET_MIN
    assert "sous-payé" in result["explanation"] or "sous le plancher" in result["explanation"]


def test_budget_sous_le_marche_est_signale_au_rh():
    """Le maximum du budget (1 700) est sous le plancher de marché (2 150)."""
    result = _analyze()
    assert "budget_below_market" in result["signals"]
    assert "risque de perdre le candidat" in result["explanation"]


# ── Règles de priorité ────────────────────────────────────────────────────────

def test_demande_au_dessus_du_budget_declenche_une_negociation():
    result = _analyze(requested_salary=2200.0, candidate_experience_years=2.0)
    assert result["verdict"] == "negotiation_required"
    assert result["budget_overrun"] == 500.0
    assert result["recommended_salary"] == BUDGET_MAX


def test_profil_exceptionnel_autorise_un_effort_borne():
    """Profil rare au-delà du budget : effort possible, plafonné à +15 %."""
    result = _analyze(
        requested_salary=2600.0, candidate_experience_years=8.0, match_score=95.0
    )
    assert result["verdict"] == "stretch"
    assert result["is_exceptional"] is True
    assert BUDGET_MAX < result["recommended_salary"] <= BUDGET_MAX * 1.15
    # Un dépassement du budget doit être annoncé explicitement.
    assert "⚠️" in result["explanation"]


def test_profil_insuffisant_declenche_une_contre_proposition():
    """Dans le budget mais sous le niveau requis : on repositionne, on n'accepte pas."""
    result = _analyze(
        requested_salary=1700.0, candidate_experience_years=0.5,
        required_experience_years=5.0, match_score=30.0,
    )
    assert result["verdict"] == "counter_offer"
    assert "underqualified" in result["signals"]
    assert BUDGET_MIN <= result["recommended_salary"] < 1700.0


def test_demande_au_dessus_du_marche_est_signalee():
    result = _analyze(requested_salary=5000.0)
    assert "above_market" in result["signals"]
    assert result["market_gap"] == 5000.0 - MARKET_MAX


def test_recommandation_jamais_silencieusement_hors_budget():
    """Tout montant recommandé au-delà du maximum doit être annoncé."""
    for requested in (1500.0, 1700.0, 2000.0, 2600.0, 6000.0):
        result = _analyze(requested_salary=requested, candidate_experience_years=8.0, match_score=95.0)
        if result["recommended_salary"] > result["budget_max"]:
            assert "dépasse le maximum du budget" in result["explanation"]


# ── Qualification : réutilise la logique du modèle de classement ──────────────

def test_qualification_reutilise_le_score_experience_du_classement():
    """La négociation et le classement doivent partager le même calcul."""
    from app.services.scoring_service import ScoringService

    service = NegotiationAnalysisService()
    # Expérience seule (pas de matching disponible).
    assert service.compute_qualification(5.9, 2.0, None) == ScoringService.compute_experience_score(2.0, 5.9)
    # Moyenne des deux signaux quand les deux existent.
    assert service.compute_qualification(1.0, 4.0, 60.0) == pytest.approx(
        (ScoringService.compute_experience_score(4.0, 1.0) + 60.0) / 2.0
    )
    # Sans aucun signal d'expérience, le matching prime.
    assert service.compute_qualification(None, 4.0, 72.0) == 72.0


def test_fourchette_inversee_est_normalisee():
    """Un RH qui saisit min et max à l'envers ne doit pas casser l'analyse."""
    result = _analyze(budget_min=1700.0, budget_max=1400.0)
    assert result["budget_min"] == 1400.0
    assert result["budget_max"] == 1700.0
    assert result["budget_overrun"] == 0.0


# ── Fourchette de marché produite par le modèle ML ────────────────────────────

@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_bandes_poste_et_candidat_sont_distinctes():
    """Un candidat senior ne transforme pas un poste ouvert à 2 ans en poste senior."""
    from app.services.salary_prediction_service import SalaryPredictionService

    bands = SalaryPredictionService().negotiation_bands(
        title="Full Stack Developer",
        skills_text="angular, java, spring, sql, docker",
        required_experience_years=2,
        candidate_experience_years=5.9,
    )
    assert bands["job"]["seniority"] < bands["candidate"]["seniority"]
    # Le marché s'interpole entre la fourchette du poste et celle du candidat,
    # au prorata de l'expérience excédentaire : (5.9 - 2) / 5.9 ≈ 0.66.
    assert bands["candidate_weight"] == pytest.approx(0.661, abs=0.01)
    assert bands["job"]["min"] < bands["market_min"] < bands["candidate"]["min"]
    assert bands["job"]["max"] < bands["market_max"] <= bands["candidate"]["max"]
    # Une fourchette, pas un point.
    assert bands["market_max"] > bands["market_min"]
    # Ordre de grandeur attendu pour un fullstack de ~6 ans sur le marché TN.
    assert 2700 <= bands["market_min"] <= 3200
    assert 3800 <= bands["market_max"] <= 4300


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_un_candidat_au_niveau_requis_ne_deplace_pas_le_marche():
    """Sans expérience excédentaire, le marché reste celui du poste."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    bands = service.negotiation_bands(
        title="Full Stack Developer", skills_text="angular, java, sql",
        required_experience_years=3, candidate_experience_years=3,
    )
    assert bands["candidate_weight"] == 0.0
    assert bands["market_min"] == bands["job"]["min"]
    assert bands["market_max"] == bands["job"]["max"]


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_un_candidat_sous_le_niveau_requis_ne_baisse_pas_le_marche():
    """Un profil junior ne dévalue pas un poste senior : le marché est celui du poste."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    bands = service.negotiation_bands(
        title="Full Stack Developer", skills_text="angular, java, sql",
        required_experience_years=6, candidate_experience_years=2,
    )
    assert bands["candidate_weight"] == 0.0
    assert bands["market_min"] == bands["job"]["min"]


def test_un_metier_nest_pas_un_niveau_de_seniorite():
    """« Architect » ou « Manager » désignent un métier, pas un palier Lead."""
    from app.services.salary_prediction_service import SalaryPredictionService as S

    # Avec une expérience connue, c'est elle qui tranche, pas l'intitulé.
    assert S._resolve_seniority("Software Architect", 7, None) == 3
    assert S._resolve_seniority("Software Architect", 12, None) == 4
    assert S._resolve_seniority("HR Manager", 6, None) == 3
    # Un marqueur explicite de niveau reste prioritaire sur l'expérience.
    assert S._resolve_seniority("Senior Java Developer", 3, None) == 3
    assert S._resolve_seniority("Tech Lead", 3, None) == 4
    # Sans expérience connue, la nature du poste sert de dernier recours.
    assert S._resolve_seniority("Engineering Manager", None, None) == 4


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_bande_de_marche_realiste_pour_le_marche_tunisien():
    """Un fullstack confirmé doit tomber dans les ordres de grandeur TN 2026."""
    from app.services.salary_prediction_service import SalaryPredictionService

    band = SalaryPredictionService().market_band({
        "title": "Full Stack Developer",
        "skills_text": "angular, java, spring, sql",
        "experience_years": 3,
    })
    assert 1800 <= band["min"] <= 2600
    assert 2600 <= band["max"] <= 3600
    assert band["min"] < band["avg"] < band["max"] or band["min"] <= band["avg"] <= band["max"]


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_bande_monotone_en_seniorite():
    """Le modèle ne doit jamais coter un senior sous un junior équivalent."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    previous = None
    for years in (1, 3, 6, 10):
        band = service.market_band({
            "title": "Backend Developer", "skills_text": "java sql", "experience_years": years,
        })
        if previous is not None:
            assert band["min"] >= previous["min"]
            assert band["max"] >= previous["max"]
        previous = band


@pytest.mark.skipif(not MODEL_FILE.exists(), reason="modèle non entraîné")
def test_le_score_de_matching_ne_deplace_pas_le_marche():
    """Le matching déplace la position DANS le marché, pas le marché lui-même."""
    from app.services.salary_prediction_service import SalaryPredictionService

    service = SalaryPredictionService()
    base = {"title": "Full Stack Developer", "skills_text": "angular java", "experience_years": 3}
    faible = service.predict_salary({**base, "candidate_match_score": 20})
    fort = service.predict_salary({**base, "candidate_match_score": 95})
    assert faible["range_min"] == fort["range_min"]
    assert faible["range_max"] == fort["range_max"]
    assert faible["predicted_salary"] <= fort["predicted_salary"]


# ══════════════════════════════════════════════════════════════════════════
#  Intégration — l'endpoint reproduit-il le cas remonté en production ?
# ══════════════════════════════════════════════════════════════════════════

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore, CVAnalysis
from app.models.user import User, UserRole

from tests.conftest import VALID_PASSWORD


async def _admin_token(client: AsyncClient, db: AsyncSession) -> str:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(
        id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="RH Test",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    ))
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
    )
    return resp.json()["access_token"]


async def _fullstack_application(db: AsyncSession) -> Application:
    """Le cas réel : poste fullstack 1 400–1 700, candidat de 5,9 ans."""
    suffixe = uuid.uuid4().hex[:8]
    user = User(
        email=f"cand_{suffixe}@example.com", username=f"cand_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Fullstack",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()

    candidate = Candidate(user_id=user.id, full_name="Candidat Fullstack")
    db.add(candidate)
    job = JobOffer(
        title="Full Stack Developer",
        description="Angular / Spring Boot",
        required_skills=["Angular", "Java", "Spring", "SQL"],
        required_experience_years=2,
        salary_min=1400, salary_max=1700,
        is_active=True,
    )
    db.add(job)
    await db.flush()

    application = Application(
        candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path="/tmp/cv.pdf", status="NEGOTIATION",
    )
    db.add(application)
    await db.flush()

    db.add(CVAnalysis(
        application_id=application.id, candidate_id=candidate.id,
        extracted_skills=["angular", "java", "spring", "sql"],
        extracted_experience_years=5.9, is_parsed=True,
    ))
    db.add(CandidateScore(
        application_id=application.id, candidate_id=candidate.id, job_offer_id=job.id,
        total_score=88.0, skills_score=90.0, experience_score=100.0, education_score=80.0,
        score_details={"extracted_years": 5.9, "required_years": 2},
    ))
    await db.commit()
    return application


@pytest.mark.asyncio
async def test_endpoint_ne_signale_aucun_depassement_au_haut_de_fourchette(
    client: AsyncClient, db: AsyncSession
):
    """
    Cas de la capture : demande 1 700 sur une offre 1 400–1 700.
    Attendu : verdict acceptable, dépassement 0 TND, position 100 %,
    et un marché rendu sous forme de FOURCHETTE.
    """
    token = await _admin_token(client, db)
    application = await _fullstack_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/negotiation-analysis",
        json={"requested_salary": 1700},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["budget_min"] == 1400 and data["budget_max"] == 1700
    assert data["budget_overrun"] == 0
    assert data["position_in_range"] == 100
    assert data["verdict"] == "acceptable"
    assert data["recommended_salary"] == 1700
    assert data["market_max"] > data["market_min"]      # fourchette, pas un point
    assert "dépasse le budget" not in data["explanation"]
    # L'expérience vient de l'instantané du modèle de classement.
    assert data["candidate_experience_years"] == 5.9
    assert data["experience_source"] == "candidate_score"


@pytest.mark.asyncio
async def test_endpoint_utilise_le_maximum_de_loffre_comme_seuil(
    client: AsyncClient, db: AsyncSession
):
    """Au-delà du maximum annoncé, et seulement là, il y a dépassement."""
    token = await _admin_token(client, db)
    application = await _fullstack_application(db)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/v1/recruitment/applications/{application.id}/negotiation-analysis"

    sous_le_max = (await client.post(url, json={"requested_salary": 1650}, headers=headers)).json()
    au_dessus = (await client.post(url, json={"requested_salary": 1900}, headers=headers)).json()

    assert sous_le_max["budget_overrun"] == 0
    assert au_dessus["budget_overrun"] == 200
    assert au_dessus["verdict"] in ("negotiation_required", "stretch")


# ══════════════════════════════════════════════════════════════════════════════
#  Jeu de scénarios — évaluation du moteur de règles sur cas de référence
# ══════════════════════════════════════════════════════════════════════════════
#
# `datasets/negotiation_scenarios.csv` décrit des situations de négociation avec
# la décision et le montant attendus. Le moteur étant à base de règles (et non
# appris), ce fichier n'est pas un jeu d'entraînement : c'est une suite de
# non-régression métier. Ajouter une ligne au CSV suffit à couvrir un cas
# nouveau, sans écrire de test.

import csv as _csv
from pathlib import Path as _Path

SCENARIOS = _Path(__file__).resolve().parents[1] / "datasets" / "negotiation_scenarios.csv"


def _optional_float(value):
    value = (value or "").strip()
    return float(value) if value else None


def _load_scenarios() -> list[dict]:
    with open(SCENARIOS, encoding="utf-8") as handle:
        return list(_csv.DictReader(handle))


def _run_scenario(row: dict) -> dict:
    return negotiation_analysis_service.analyze(
        candidate_name=row["scenario"],
        budget_min=float(row["company_budget_min"]),
        budget_max=float(row["company_budget_max"]),
        requested_salary=float(row["candidate_requested_salary"]),
        market_min=float(row["market_salary_min"]),
        market_max=float(row["market_salary_max"]),
        market_reference=(float(row["market_salary_min"]) + float(row["market_salary_max"])) / 2,
        candidate_experience_years=_optional_float(row["candidate_experience"]),
        required_experience_years=_optional_float(row["required_experience"]),
        match_score=_optional_float(row["matching_score"]),
        seniority_label=row["job_level"],
    )


def test_le_fichier_de_scenarios_est_exploitable():
    scenarios = _load_scenarios()
    assert len(scenarios) >= 15
    assert {"candidate_experience", "required_experience", "matching_score",
            "market_salary_min", "market_salary_max", "company_budget_min",
            "company_budget_max", "candidate_requested_salary", "job_level",
            "expected_decision", "expected_recommendation"} <= set(scenarios[0])


@pytest.mark.parametrize("row", _load_scenarios(), ids=lambda r: r["scenario"])
def test_scenario_de_negociation(row):
    """Chaque scénario doit produire la décision et le montant attendus."""
    result = _run_scenario(row)
    assert result["decision"] == row["expected_decision"], (
        f"{row['scenario']} : attendu {row['expected_decision']}, "
        f"obtenu {result['decision']} — {row['comment']}"
    )
    assert result["recommended_salary"] == pytest.approx(
        float(row["expected_recommendation"]), abs=50
    ), f"{row['scenario']} — {row['comment']}"


def test_le_score_de_negociation_est_borne_et_pondere():
    """Score sur 100, somme des quatre composantes pondérées 30/30/20/20."""
    for row in _load_scenarios():
        result = _run_scenario(row)
        assert 0.0 <= result["negotiation_score"] <= 100.0
        breakdown = result["score_breakdown"]
        assert sum(breakdown["weights"].values()) == pytest.approx(1.0)
        for component in ("experience", "market_position", "budget"):
            assert 0.0 <= breakdown[component] <= 100.0


def test_le_score_recompense_un_meilleur_profil():
    """À situation budgétaire identique, un profil plus fort score plus haut."""
    faible = _analyze(candidate_experience_years=1.0, required_experience_years=5.0, match_score=35.0)
    fort = _analyze(candidate_experience_years=8.0, required_experience_years=5.0, match_score=95.0)
    assert fort["negotiation_score"] > faible["negotiation_score"]


def test_le_score_penalise_un_depassement_budgetaire():
    """À profil identique, demander plus que le budget dégrade le score."""
    dans_budget = _analyze(requested_salary=1600.0)
    hors_budget = _analyze(requested_salary=2600.0)
    assert hors_budget["negotiation_score"] < dans_budget["negotiation_score"]
