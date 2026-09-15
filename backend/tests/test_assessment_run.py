"""
Lot 2 — passage du test : progression imposée, chronométrage serveur.

La vérification du lot tient en trois attaques qui doivent toutes échouer :

1. **Sauter une question** — répondre à la 5 sans avoir traité la 4.
2. **Soumettre après l'expiration** — la limite `started_at + duration` est
   posée par le serveur, quoi qu'affiche le navigateur.
3. **Lire les questions à venir** — le serveur n'en sert qu'une à la fois, et
   jamais avec sa bonne réponse.

S'y ajoute ce qui découle de la progression imposée : une réponse est
définitive, « Passer » compte comme une erreur, et le candidat n'apprend jamais
s'il a eu juste.
"""
import json
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.assessment import (
    AnswerOutcome, QuestionDifficulty, QuestionStatus, SessionStatus,
    TestAnswer, TestSession,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole
from app.services.assessment_service import assessment_service as svc, sweep_expired_sessions
from app.utils.helpers import as_utc, utcnow

from tests.conftest import VALID_PASSWORD

PUBLIC = "/api/v1/assessment/public"


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _offre(db: AsyncSession) -> JobOffer:
    job = JobOffer(
        title="Développeur Full Stack", description="Poste de test.",
        required_skills=["Angular", "Java", "SQL"], required_experience_years=2,
        is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def _candidature(db: AsyncSession, job: JobOffer) -> Application:
    suffixe = uuid.uuid4().hex[:8]
    user = User(
        email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Test",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name="Candidat Test")
    db.add(candidat)
    await db.flush()
    app_ = Application(candidate_id=candidat.id, job_offer_id=job.id,
                       cv_file_path="/tmp/cv.pdf", status="REVIEWED")
    db.add(app_)
    await db.commit()
    await db.refresh(app_)
    return app_


async def _session(db: AsyncSession, n=4, duration=20) -> TestSession:
    job = await _offre(db)
    difficultes = [QuestionDifficulty.FACILE, QuestionDifficulty.MOYENNE,
                   QuestionDifficulty.DIFFICILE]
    questions = []
    for i in range(n):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question numéro {i} sur le poste ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
            "explanation": "Secret de correction.",
            "difficulty": difficultes[i % 3], "skill_tag": ["angular", "java", "sql"][i % 3],
        })
        q.status = QuestionStatus.ACTIVE
        questions.append(q)
    await db.commit()
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id,
                                       [q.id for q in questions], duration_minutes=duration)
    await db.commit()
    await db.refresh(session)
    return session


async def _rh_token(client: AsyncClient, db: AsyncSession) -> str:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(
        id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="RH Test",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    ))
    await db.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": VALID_PASSWORD})
    return resp.json()["access_token"]


# ══════════════════════════════════════════════════════════════════════════════
#  Les trois attaques
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_attaque_1_sauter_une_question_echoue(client: AsyncClient, db: AsyncSession):
    """On ne répond qu'à la question en cours, jamais à la suivante."""
    session = await _session(db, n=4)
    depart = (await client.post(f"{PUBLIC}/{session.token}/start")).json()
    assert depart["next_question"]["position"] == 1

    resp = await client.post(f"{PUBLIC}/{session.token}/answer",
                             json={"position": 3, "answer": ["B"]})
    assert resp.status_code == 409
    assert "question 1" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_attaque_2_soumettre_apres_expiration_echoue(
    client: AsyncClient, db: AsyncSession
):
    """`started_at + duration` fait foi, quoi qu'affiche le navigateur."""
    session = await _session(db, n=4, duration=20)
    await client.post(f"{PUBLIC}/{session.token}/start")

    # On recule le départ au-delà de la limite : le serveur doit refuser.
    session_db = (await db.execute(
        select(TestSession).where(TestSession.id == session.id)
    )).scalar_one()
    session_db.started_at = utcnow() - timedelta(minutes=25)
    await db.commit()

    resp = await client.post(f"{PUBLIC}/{session.token}/answer",
                             json={"position": 1, "answer": ["B"]})
    assert resp.status_code == 410

    await db.refresh(session_db)
    assert session_db.status == SessionStatus.EXPIRE
    assert session_db.score is not None, "la session doit être corrigée en l'état"


@pytest.mark.asyncio
async def test_attaque_3_les_questions_a_venir_ne_fuient_pas(
    client: AsyncClient, db: AsyncSession
):
    """
    Le serveur ne sert qu'une question à la fois, et jamais sa bonne réponse.
    Sinon tout le test se lit dans l'onglet réseau.
    """
    session = await _session(db, n=4)
    corps = (await client.post(f"{PUBLIC}/{session.token}/start")).json()
    question = corps["next_question"]

    assert question["position"] == 1
    assert question["total"] == 4
    for champ in ("correct_answer", "explanation", "expected_seconds", "difficulty"):
        assert champ not in question, f"« {champ} » ne doit jamais atteindre le candidat"

    # Une seule question par réponse. On compte les énoncés plutôt que d'en
    # chercher un en particulier : `create_session` mélange l'ordre, donc
    # l'énoncé « numéro 2 » peut parfaitement occuper la position 1.
    corps = (await client.post(f"{PUBLIC}/{session.token}/start")).json()
    brut = json.dumps(corps, ensure_ascii=False)
    assert "Secret de correction" not in brut
    assert brut.count("sur le poste ?") == 1, "une seule question à la fois"
    # Et c'est bien la MÊME : rafraîchir la page ne fait pas sauter un tour.
    assert corps["next_question"]["position"] == 1
    assert corps["next_question"]["statement"] == question["statement"]


# ══════════════════════════════════════════════════════════════════════════════
#  Progression imposée
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_parcours_avance_question_par_question(
    client: AsyncClient, db: AsyncSession
):
    session = await _session(db, n=4)
    corps = (await client.post(f"{PUBLIC}/{session.token}/start")).json()

    vues = []
    while not corps["finished"]:
        position = corps["next_question"]["position"]
        vues.append(position)
        corps = (await client.post(f"{PUBLIC}/{session.token}/answer",
                                   json={"position": position, "answer": ["B"]})).json()

    assert vues == [1, 2, 3, 4]
    assert corps["next_question"] is None


@pytest.mark.asyncio
async def test_une_reponse_est_definitive(client: AsyncClient, db: AsyncSession):
    """Pas de correction après coup : la progression ne revient pas en arrière."""
    session = await _session(db, n=4)
    await client.post(f"{PUBLIC}/{session.token}/start")
    await client.post(f"{PUBLIC}/{session.token}/answer",
                      json={"position": 1, "answer": ["A"]})

    resp = await client.post(f"{PUBLIC}/{session.token}/answer",
                             json={"position": 1, "answer": ["B"]})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_passer_compte_comme_une_erreur(client: AsyncClient, db: AsyncSession):
    """Zéro point comme une réponse fausse, mais distinguable à la relecture."""
    session = await _session(db, n=4)
    await client.post(f"{PUBLIC}/{session.token}/start")
    for position in range(1, 5):
        await client.post(f"{PUBLIC}/{session.token}/answer",
                          json={"position": position, "answer": None})

    session_db = (await db.execute(
        select(TestSession).options(selectinload(TestSession.answers))
        .where(TestSession.id == session.id)
    )).scalar_one()
    assert session_db.score == 0.0
    assert all(r.outcome == AnswerOutcome.PASSEE for r in session_db.answers)


@pytest.mark.asyncio
async def test_le_candidat_napprend_jamais_sil_a_juste(
    client: AsyncClient, db: AsyncSession
):
    """L'apprendre question après question reviendrait à livrer le vivier."""
    session = await _session(db, n=4)
    await client.post(f"{PUBLIC}/{session.token}/start")
    resp = await client.post(f"{PUBLIC}/{session.token}/answer",
                             json={"position": 1, "answer": ["B"]})
    corps = resp.json()
    assert set(corps) == {"accepted", "next_question", "finished"}
    assert "correct" not in resp.text.lower() or "correcte" not in resp.text


@pytest.mark.asyncio
async def test_la_fin_du_test_ne_montre_aucune_note(
    client: AsyncClient, db: AsyncSession
):
    session = await _session(db, n=2)
    await client.post(f"{PUBLIC}/{session.token}/start")
    for position in (1, 2):
        await client.post(f"{PUBLIC}/{session.token}/answer",
                          json={"position": position, "answer": ["B"]})

    resp = await client.post(f"{PUBLIC}/{session.token}/finish")
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["finished"] is True
    assert "score" not in corps


# ══════════════════════════════════════════════════════════════════════════════
#  Chronométrage serveur
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_chronometre_demarre_a_louverture_pas_a_lenvoi(
    client: AsyncClient, db: AsyncSession
):
    """La limite court quand le candidat ouvre vraiment le test."""
    session = await _session(db, n=2)
    assert session.started_at is None

    await client.get(f"{PUBLIC}/{session.token}")
    session_db = (await db.execute(
        select(TestSession).where(TestSession.id == session.id))).scalar_one()
    assert session_db.started_at is None, "l'écran d'accueil ne démarre pas le test"

    await client.post(f"{PUBLIC}/{session.token}/start")
    await db.refresh(session_db)
    assert session_db.started_at is not None
    assert session_db.status == SessionStatus.EN_COURS


@pytest.mark.asyncio
async def test_rafraichir_la_page_ne_remet_pas_le_chronometre_a_zero(
    client: AsyncClient, db: AsyncSession
):
    session = await _session(db, n=3)
    await client.post(f"{PUBLIC}/{session.token}/start")
    reponse = (await db.execute(
        select(TestAnswer).where(TestAnswer.session_id == session.id,
                                 TestAnswer.position == 1))).scalar_one()
    premier_envoi = reponse.served_at
    assert premier_envoi is not None

    await client.post(f"{PUBLIC}/{session.token}/start")
    await db.refresh(reponse)
    # `as_utc` des deux côtés : la valeur relue de SQLite est sans fuseau,
    # celle posée en Python en a un. Ce sont pourtant le même instant.
    assert as_utc(reponse.served_at) == as_utc(premier_envoi)


@pytest.mark.asyncio
async def test_le_client_ne_peut_pas_fournir_de_duree(
    client: AsyncClient, db: AsyncSession
):
    """
    Un temps calculé en JavaScript se réécrit en trois lignes dans la console :
    le schéma n'accepte aucun champ de durée.
    """
    session = await _session(db, n=2)
    await client.post(f"{PUBLIC}/{session.token}/start")
    resp = await client.post(
        f"{PUBLIC}/{session.token}/answer",
        json={"position": 1, "answer": ["B"], "elapsed_seconds": 1, "overrun_seconds": 0},
    )
    assert resp.status_code == 200

    reponse = (await db.execute(
        select(TestAnswer).where(TestAnswer.session_id == session.id,
                                 TestAnswer.position == 1))).scalar_one()
    assert reponse.overrun_seconds == 0
    assert reponse.answered_at is not None


@pytest.mark.asyncio
async def test_le_temps_restant_est_global(client: AsyncClient, db: AsyncSession):
    """Seule information de temps donnée au candidat."""
    session = await _session(db, n=3, duration=20)
    corps = (await client.post(f"{PUBLIC}/{session.token}/start")).json()
    restant = corps["next_question"]["seconds_remaining"]
    assert 20 * 60 - 30 <= restant <= 20 * 60


@pytest.mark.asyncio
async def test_le_balayage_clot_les_sessions_abandonnees(db: AsyncSession):
    """
    Sans lui, un candidat qui ferme son navigateur laisse sa session EN_COURS
    indéfiniment — jamais corrigée, jamais visible comme terminée côté RH.
    """
    session = await _session(db, n=3, duration=20)
    session_db = (await db.execute(
        select(TestSession).where(TestSession.id == session.id))).scalar_one()
    session_db.status = SessionStatus.EN_COURS
    session_db.started_at = utcnow() - timedelta(minutes=30)
    await db.commit()

    traitees = await sweep_expired_sessions(db)
    assert traitees >= 1
    await db.refresh(session_db)
    assert session_db.status == SessionStatus.EXPIRE
    assert session_db.score == 0.0


@pytest.mark.asyncio
async def test_un_lien_perime_ne_souvre_pas(client: AsyncClient, db: AsyncSession):
    session = await _session(db, n=2)
    session_db = (await db.execute(
        select(TestSession).where(TestSession.id == session.id))).scalar_one()
    session_db.link_expires_at = utcnow() - timedelta(hours=1)
    await db.commit()

    resp = await client.post(f"{PUBLIC}/{session.token}/start")
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_un_jeton_inconnu_donne_404(client: AsyncClient):
    assert (await client.get(f"{PUBLIC}/jeton-qui-nexiste-pas")).status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Back-office
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_les_resultats_sont_reserves_au_rh(client: AsyncClient, db: AsyncSession):
    session = await _session(db, n=2)
    url = f"/api/v1/assessment/applications/{session.application_id}/session"
    assert (await client.get(url)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_le_detail_des_reponses_donne_la_reussite_par_competence(
    client: AsyncClient, db: AsyncSession
):
    """
    La vue qui sert vraiment à l'entretien : savoir qu'un candidat tient
    Angular et bute sur SQL vaut mieux que de savoir qu'il a 65.
    """
    session = await _session(db, n=3)
    await client.post(f"{PUBLIC}/{session.token}/start")
    # Juste sur la 1, faux sur la 2, passé sur la 3.
    for position, reponse in ((1, ["B"]), (2, ["A"]), (3, None)):
        await client.post(f"{PUBLIC}/{session.token}/answer",
                          json={"position": position, "answer": reponse})

    token = await _rh_token(client, db)
    resp = await client.get(
        f"/api/v1/assessment/applications/{session.application_id}/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    corps = resp.json()

    assert corps["outcome_counts"]["CORRECTE"] == 1
    assert corps["outcome_counts"]["FAUSSE"] == 1
    assert corps["outcome_counts"]["PASSEE"] == 1
    assert len(corps["answers"]) == 3
    assert corps["answers"][0]["correct_answer"] == ["B"]
    assert corps["answers"][0]["elapsed_seconds"] is not None
    assert {s["skill"] for s in corps["by_skill"]} == {"angular", "java", "sql"}


@pytest.mark.asyncio
async def test_la_preparation_propose_et_signale_les_manques(
    client: AsyncClient, db: AsyncSession
):
    session = await _session(db, n=4)
    token = await _rh_token(client, db)
    resp = await client.get(
        f"/api/v1/assessment/applications/{session.application_id}/prepare?count=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert len(corps["questions"]) == 3
    assert "competences_manquantes" in corps["coverage"]
    assert corps["coverage"]["total"] == 3


@pytest.mark.asyncio
async def test_lenvoi_bascule_la_candidature_et_prepare_le_courriel(
    client: AsyncClient, db: AsyncSession, monkeypatch
):
    """
    Ce que l'envoi doit produire, au-delà de la session elle-même.

    Le back-office se sert du statut `TEST_SENT` pour savoir s'il doit ouvrir
    une candidature sur la préparation ou sur les résultats. Et sans courriel,
    le candidat n'a aucun moyen d'atteindre son lien : la page est publique
    mais son jeton n'est nulle part ailleurs.
    """
    job = await _offre(db)
    questions = []
    for i in range(3):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question envoyée numéro {i} ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
        })
        q.status = QuestionStatus.ACTIVE
        questions.append(q)
    application = await _candidature(db, job)
    await db.commit()

    envois: list[dict] = []
    import app.services.email_service as email_service
    monkeypatch.setattr(
        email_service, "send_technical_test_invitation",
        lambda **kw: envois.append(kw) or True,
    )

    token = await _rh_token(client, db)
    resp = await client.post(
        f"/api/v1/assessment/applications/{application.id}/send",
        json={"question_ids": [str(q.id) for q in questions], "duration_minutes": 15},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    corps = resp.json()
    assert corps["question_count"] == 3
    assert corps["duration_minutes"] == 15
    assert corps["status"] == "ENVOYE"

    # Le statut est ce sur quoi le back-office se règle.
    await db.refresh(application)
    assert application.status == "TEST_SENT"

    assert len(envois) == 1, "le candidat doit recevoir son lien"
    courriel = envois[0]
    assert courriel["question_count"] == 3
    assert courriel["duration_minutes"] == 15
    assert courriel["token"], "sans jeton, le lien ne mène nulle part"
    # Le jeton de la session, et pas un autre : c'est le seul chemin d'accès.
    session = (await db.execute(
        select(TestSession).where(TestSession.application_id == application.id)
    )).scalars().one()
    assert courriel["token"] == session.token
