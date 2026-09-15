"""
Lots 4 et 5 — évaluation d'entretien assistée et score composite.

Deux vérifications, et la seconde est celle qui compte le plus.

**Lot 4** — la proposition du modèle et la décision du recruteur sont stockées
séparément. Les confondre interdirait de savoir plus tard si le RH a suivi la
suggestion, et donc de mesurer si cette suggestion vaut quelque chose.

**Lot 5** — une note manquante n'est pas un zéro. Un candidat qui n'a pas encore
passé l'entretien ne doit pas chuter au classement : le composite se calcule sur
les volets disponibles, renormalisés, et la complétude accompagne toujours la
note.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.assessment import SessionStatus, TestSession
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.composite_score_service import (
    DEFAULT_WEIGHTS, composite_score_service as composite,
)
from app.services.interview_evaluation_service import (
    CRITERIA, interview_evaluation_service as evaluation,
)

from tests.conftest import VALID_PASSWORD


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _candidature(db: AsyncSession, *, cv=None) -> Application:
    suffixe = uuid.uuid4().hex[:8]
    user = User(
        email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name="Candidat")
    db.add(candidat)
    job = JobOffer(title="Développeur", description="Poste de test.",
                   required_skills=["Java"], is_active=True, status="PUBLISHED")
    db.add(job)
    await db.flush()
    application = Application(candidate_id=candidat.id, job_offer_id=job.id,
                              cv_file_path="/tmp/cv.pdf", status="REVIEWED")
    db.add(application)
    await db.flush()
    if cv is not None:
        db.add(CandidateScore(
            application_id=application.id, job_offer_id=job.id,
            candidate_id=candidat.id, total_score=cv,
            skills_score=cv, experience_score=cv, education_score=cv,
        ))
    await db.commit()
    await db.refresh(application)
    return application


async def _rh(client: AsyncClient, db: AsyncSession) -> dict:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(
        id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    ))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════════
#  Lot 5 — le composite
# ══════════════════════════════════════════════════════════════════════════════

def test_une_note_manquante_nest_pas_un_zero():
    """
    Le cœur du lot. CV 80, test 60, entretien non passé :
    (80×0.30 + 60×0.35) / 0.65 = 69,2 — et non 45, qui serait le résultat si
    l'entretien manquant comptait pour zéro.
    """
    resultat = composite.compute(cv_score=80, test_score=60, interview_score=None)
    assert resultat["score"] == 69.2
    assert resultat["completeness"] == 2
    assert resultat["missing"] == ["interview"]


def test_le_zero_reste_un_zero():
    """Un candidat réellement noté 0 à l'entretien doit être noté 0."""
    resultat = composite.compute(cv_score=80, test_score=60, interview_score=0)
    assert resultat["completeness"] == 3
    assert resultat["score"] < 50
    assert resultat["missing"] == []


def test_les_trois_volets_sont_ponderes_30_35_35():
    resultat = composite.compute(cv_score=100, test_score=0, interview_score=0)
    assert resultat["score"] == pytest.approx(DEFAULT_WEIGHTS["cv"] * 100, abs=0.1)


def test_les_poids_affiches_sont_ceux_apres_renormalisation():
    """
    Sur deux volets, le CV ne pèse plus 0.30 mais 0.46. Afficher le poids
    nominal laisserait croire que la note manquante a compté.
    """
    resultat = composite.compute(cv_score=80, test_score=60, interview_score=None)
    poids = {k: v["weight"] for k, v in resultat["breakdown"].items()}
    assert poids["cv"] == pytest.approx(0.30 / 0.65, abs=0.01)
    assert sum(poids.values()) == pytest.approx(1.0, abs=0.01)


def test_un_seul_volet_donne_ce_volet():
    resultat = composite.compute(cv_score=72, test_score=None, interview_score=None)
    assert resultat["score"] == 72.0
    assert resultat["completeness"] == 1


def test_aucun_volet_ne_donne_pas_zero_mais_rien():
    """« Pas encore évalué » et « nul » sont deux choses différentes."""
    resultat = composite.compute(cv_score=None, test_score=None, interview_score=None)
    assert resultat["score"] is None
    assert resultat["completeness"] == 0
    assert resultat["band"] == "indisponible"


def test_un_candidat_sans_entretien_ne_chute_pas_au_classement():
    """
    La vérification du lot 5. Deux candidats identiques sur CV et test ; l'un a
    passé l'entretien, l'autre non. Celui qui attend ne doit pas s'effondrer.
    """
    complet = composite.compute(cv_score=80, test_score=70, interview_score=75)
    en_cours = composite.compute(cv_score=80, test_score=70, interview_score=None)
    assert abs(complet["score"] - en_cours["score"]) < 10
    assert en_cours["score"] > 70


def test_la_lecture_se_fait_par_bandes():
    """
    La précision du composite ne justifie pas de distinguer 74 de 71 ; elle
    justifie de distinguer un dossier solide d'un dossier fragile.
    """
    assert composite.band(88) == "solide"
    assert composite.band(62) == "correct"
    assert composite.band(42) == "fragile"
    assert composite.band(20) == "insuffisant"
    assert composite.band(None) == "indisponible"


def test_la_marge_dincertitude_est_annoncee():
    resultat = composite.compute(cv_score=74, test_score=74, interview_score=74)
    assert resultat["uncertainty"] >= 5, "annoncer 74 sans marge suggère une exactitude inexistante"


def test_des_ponderations_sur_mesure_sont_respectees():
    resultat = composite.compute(
        cv_score=100, test_score=0, interview_score=0,
        weights={"cv": 0.6, "test": 0.2, "interview": 0.2},
    )
    assert resultat["score"] == pytest.approx(60.0, abs=0.1)


@pytest.mark.asyncio
async def test_le_composite_reprend_la_derniere_session_terminee(db: AsyncSession):
    """Une session encore en cours n'a pas de note : la reprendre noterait un
    candidat sur un test qu'il n'a pas fini."""
    from datetime import timedelta
    from app.utils.helpers import utcnow

    application = await _candidature(db, cv=80)
    db.add(TestSession(
        application_id=application.id, token=uuid.uuid4().hex,
        status=SessionStatus.TERMINE, score=64.0,
        link_expires_at=utcnow() + timedelta(hours=72),
        submitted_at=utcnow() - timedelta(hours=1),
    ))
    db.add(TestSession(
        application_id=application.id, token=uuid.uuid4().hex,
        status=SessionStatus.EN_COURS, score=None,
        link_expires_at=utcnow() + timedelta(hours=72),
    ))
    await db.commit()

    score = await composite.refresh(db, application.id)
    await db.commit()
    assert score.test_score == 64.0
    assert score.composite_completeness == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Lot 4 — l'évaluation d'entretien
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_la_note_dentretien_est_celle_du_rh(db: AsyncSession):
    application = await _candidature(db, cv=70)
    score = await evaluation.set_score(db, application.id, 82.0, notes="Bon échange.")
    await db.commit()
    assert score.interview_score == 82.0
    assert score.interview_notes == "Bon échange."


@pytest.mark.asyncio
async def test_la_note_peut_etre_effacee(db: AsyncSession):
    """Le RH doit pouvoir revenir sur sa décision."""
    application = await _candidature(db, cv=70)
    await evaluation.set_score(db, application.id, 82.0)
    score = await evaluation.set_score(db, application.id, None)
    await db.commit()
    assert score.interview_score is None


@pytest.mark.asyncio
async def test_une_note_hors_bornes_est_refusee(db: AsyncSession):
    from fastapi import HTTPException
    application = await _candidature(db, cv=70)
    for valeur in (-5, 140):
        with pytest.raises(HTTPException):
            await evaluation.set_score(db, application.id, valeur)


@pytest.mark.asyncio
async def test_un_entretien_est_notable_sans_analyse_de_cv(db: AsyncSession):
    """Le RH doit pouvoir noter même si l'analyse automatique n'a pas tourné."""
    application = await _candidature(db, cv=None)
    score = await evaluation.set_score(db, application.id, 75.0)
    await db.commit()
    assert score.interview_score == 75.0
    assert score.total_score == 0.0


@pytest.mark.asyncio
async def test_sans_modele_la_proposition_nest_pas_bloquante(db: AsyncSession):
    """Un entretien ne doit pas rester en attente parce qu'une API est absente."""
    if evaluation.llm_enabled:
        pytest.skip("Une clé LLM est configurée sur cet environnement.")
    application = await _candidature(db, cv=70)
    proposition = await evaluation.suggest(
        db, application.id, "Le candidat a bien expliqué son parcours et ses projets."
    )
    await db.commit()
    assert proposition["available"] is False
    assert "directement" in proposition["reason"]


@pytest.mark.asyncio
async def test_des_notes_trop_courtes_sont_refusees(db: AsyncSession):
    from fastapi import HTTPException
    application = await _candidature(db, cv=70)
    with pytest.raises(HTTPException):
        await evaluation.suggest(db, application.id, "ok")


def test_la_proposition_recalcule_sa_moyenne():
    """
    Les modèles se trompent en arithmétique. Une moyenne fausse
    décrédibiliserait toute la suggestion : on la recalcule.
    """
    brut = """```json
    {"criteria":{"communication":{"score":80,"justification":"Clair."},
     "technique":{"score":60,"justification":"Hésitant sur SQL."},
     "adequation":{"score":null,"justification":"Non abordé."},
     "motivation":{"score":70,"justification":"Projet cohérent."}},
     "overall":99,"summary":"Profil correct."}
    ```"""
    propose = evaluation._parser(brut)
    assert propose["overall"] == 70.0, "la moyenne annoncée (99) doit être ignorée"
    assert propose["criteria"]["adequation"]["score"] is None


def test_un_critere_non_aborde_nest_pas_note_zero():
    """N'inventer aucune note : « non abordé » n'est pas « nul »."""
    brut = ('{"criteria":{"communication":{"score":80,"justification":"x"}},'
            '"overall":80,"summary":""}')
    propose = evaluation._parser(brut)
    assert set(propose["criteria"]) == set(CRITERIA)
    assert propose["criteria"]["technique"]["score"] is None
    assert propose["overall"] == 80.0


def test_une_reponse_illisible_ne_casse_rien():
    assert evaluation._parser("Désolé, je ne peux pas.") is None
    assert evaluation._parser("") is None
    assert evaluation._parser('{"criteria":{}}') is None


# ══════════════════════════════════════════════════════════════════════════════
#  Bout en bout, via l'API
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_levaluation_est_reservee_au_rh(client: AsyncClient, db: AsyncSession):
    application = await _candidature(db, cv=70)
    url = f"/api/v1/assessment/applications/{application.id}/evaluation"
    assert (await client.get(url)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_le_parcours_dentretien_bout_en_bout(client: AsyncClient, db: AsyncSession):
    application = await _candidature(db, cv=80)
    entete = await _rh(client, db)
    base = f"/api/v1/assessment/applications/{application.id}"

    # Un seul volet au départ : le CV.
    corps = (await client.get(f"{base}/evaluation", headers=entete)).json()
    assert corps["composite"]["completeness"] == 1
    assert corps["composite"]["score"] == 80.0

    # Notes libres, puis note du RH.
    notes = "Candidat clair sur son parcours. Hésitant sur les jointures SQL."
    resp = await client.post(f"{base}/interview/notes", json={"notes": notes}, headers=entete)
    assert resp.status_code == 200
    assert resp.json()["interview_notes"] == notes

    resp = await client.post(f"{base}/interview/score",
                             json={"interview_score": 72}, headers=entete)
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["interview_score"] == 72.0
    assert corps["composite"]["completeness"] == 2
    assert corps["composite"]["missing"] == ["test"]
    assert corps["composite"]["band"] in ("solide", "correct")


@pytest.mark.asyncio
async def test_la_suggestion_ne_devient_jamais_la_note(
    client: AsyncClient, db: AsyncSession
):
    """
    La distinction qui fait tout le lot 4 : proposer n'est pas décider. Tant
    que le RH n'a pas tranché, `interview_score` reste vide.
    """
    application = await _candidature(db, cv=80)
    entete = await _rh(client, db)
    base = f"/api/v1/assessment/applications/{application.id}"

    await client.post(f"{base}/interview/suggest", headers=entete, json={
        "notes": "Le candidat a bien expliqué son parcours, un peu hésitant sur SQL.",
    })
    corps = (await client.get(f"{base}/evaluation", headers=entete)).json()
    assert corps["interview_score"] is None, "une suggestion ne décide de rien"
    assert corps["composite"]["completeness"] == 1
