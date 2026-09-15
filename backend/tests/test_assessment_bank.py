"""
Lot 1 — socle du test technique : vivier, tirage, correction, notation.

Aucun LLM ici. Les questions sont écrites à la main, ce qui permet de valider
le modèle de données et le barème AVANT d'y ajouter une source d'erreur. Si le
score est faux à ce stade, rien de ce qui suit ne tiendra.

La vérification du lot : créer des questions, tirer un test, répondre, obtenir
une note juste.
"""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.assessment import (
    AnswerOutcome, QuestionDifficulty, QuestionKind, QuestionStatus,
    SessionStatus, TestAnswer, TestSession,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User
from app.core.security import hash_password
from app.services.assessment_service import assessment_service as svc
from app.utils.helpers import utcnow

from tests.conftest import VALID_PASSWORD


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _offre(db: AsyncSession, skills=None) -> JobOffer:
    job = JobOffer(
        title="Développeur Full Stack",
        description="Poste de test.",
        required_skills=skills if skills is not None else ["Angular", "Java", "SQL"],
        required_experience_years=2,
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
    application = Application(
        candidate_id=candidat.id, job_offer_id=job.id,
        cv_file_path="/tmp/cv.pdf", status="REVIEWED",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


def _qcm(statement="Que fait `git rebase` ?", correct="B", skill=None,
         difficulty=QuestionDifficulty.MOYENNE) -> dict:
    return {
        "statement": statement,
        "options": ["A", "B", "C", "D"],
        "correct_answer": [correct],
        "explanation": "Parce que.",
        "difficulty": difficulty,
        "kind": QuestionKind.QCM_UNIQUE,
        "skill_tag": skill,
    }


async def _vivier(db: AsyncSession, job: JobOffer, n=12, skills=None) -> list:
    """n questions ACTIVE, réparties sur les trois difficultés."""
    difficultes = [QuestionDifficulty.FACILE, QuestionDifficulty.MOYENNE,
                   QuestionDifficulty.DIFFICILE]
    skills = skills or ["angular", "java", "sql"]
    questions = []
    for i in range(n):
        q = await svc.create_question(db, job.id, _qcm(
            statement=f"Question {i}", skill=skills[i % len(skills)],
            difficulty=difficultes[i % 3],
        ))
        q.status = QuestionStatus.ACTIVE
        questions.append(q)
    await db.commit()
    return questions


# ── Vivier ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_question_manuelle_nait_validee(db: AsyncSession):
    """Écrite par un humain, elle n'a pas besoin d'une relecture humaine."""
    job = await _offre(db)
    q = await svc.create_question(db, job.id, _qcm())
    await db.commit()
    assert q.status == QuestionStatus.VALIDEE
    assert q.generated_by == "manuel"


@pytest.mark.asyncio
async def test_une_question_generee_nait_a_relire(db: AsyncSession):
    """C'est la seule barrière entre une fausse bonne réponse et un candidat lésé."""
    job = await _offre(db)
    q = await svc.create_question(db, job.id, _qcm(), generated_by="llm:gemini")
    await db.commit()
    assert q.status == QuestionStatus.GENEREE


@pytest.mark.asyncio
async def test_le_budget_de_temps_suit_la_difficulte(db: AsyncSession):
    job = await _offre(db)
    facile = await svc.create_question(db, job.id, _qcm(difficulty=QuestionDifficulty.FACILE))
    dur = await svc.create_question(db, job.id, _qcm(difficulty=QuestionDifficulty.DIFFICILE))
    await db.commit()
    assert facile.expected_seconds == 60
    assert dur.expected_seconds == 150


@pytest.mark.asyncio
async def test_une_bonne_reponse_hors_options_est_refusee(db: AsyncSession):
    """L'erreur type d'un modèle : la bonne réponse n'est pas dans la liste."""
    job = await _offre(db)
    with pytest.raises(HTTPException) as exc:
        await svc.create_question(db, job.id, {
            **_qcm(), "correct_answer": ["Z"],
        })
    assert exc.value.status_code == 400
    assert "propositions" in exc.value.detail


@pytest.mark.asyncio
async def test_un_qcm_unique_a_exactement_une_bonne_reponse(db: AsyncSession):
    job = await _offre(db)
    with pytest.raises(HTTPException):
        await svc.create_question(db, job.id, {**_qcm(), "correct_answer": ["A", "B"]})


@pytest.mark.asyncio
async def test_un_qcm_demande_au_moins_deux_propositions(db: AsyncSession):
    job = await _offre(db)
    with pytest.raises(HTTPException):
        await svc.create_question(db, job.id, {
            **_qcm(), "options": ["A"], "correct_answer": ["A"],
        })


@pytest.mark.asyncio
async def test_activer_le_vivier(db: AsyncSession):
    job = await _offre(db)
    for i in range(3):
        await svc.create_question(db, job.id, _qcm(statement=f"Q{i}"))
    await db.commit()
    n = await svc.activate_bank(db, job.id, validated_by=uuid.uuid4())
    await db.commit()
    assert n == 3
    actives = await svc.list_questions(db, job.id, [QuestionStatus.ACTIVE])
    assert len(actives) == 3
    assert all(q.validated_at for q in actives)


# ── Tirage ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_tirage_respecte_le_gabarit_de_difficulte(db: AsyncSession):
    job = await _offre(db)
    await _vivier(db, job, n=30)
    retenues = await svc.recommend_questions(db, job.id, count=12)
    assert len(retenues) == 12
    par_diff = {}
    for q in retenues:
        par_diff[q.difficulty] = par_diff.get(q.difficulty, 0) + 1
    assert par_diff[QuestionDifficulty.FACILE] == 4
    assert par_diff[QuestionDifficulty.MOYENNE] == 5
    assert par_diff[QuestionDifficulty.DIFFICILE] == 3


@pytest.mark.asyncio
async def test_le_tirage_couvre_toutes_les_competences(db: AsyncSession):
    """
    Sans cette règle, un tirage plausible donne douze questions Angular et
    aucune sur SQL — le test ne mesure plus le poste.
    """
    job = await _offre(db, skills=["Angular", "Java", "SQL"])
    await _vivier(db, job, n=30, skills=["angular", "java", "sql"])
    retenues = await svc.recommend_questions(db, job.id, count=12)
    couvertes = {q.skill_tag for q in retenues}
    assert {"angular", "java", "sql"} <= couvertes


@pytest.mark.asyncio
async def test_le_tirage_prefere_les_questions_les_moins_servies(db: AsyncSession):
    """Le vivier doit tourner, pas resservir éternellement les mêmes douze."""
    job = await _offre(db)
    questions = await _vivier(db, job, n=20)
    for q in questions[:10]:
        q.times_served = 50
    await db.commit()

    retenues = await svc.recommend_questions(db, job.id, count=6)
    usees = sum(1 for q in retenues if q.times_served == 50)
    assert usees <= 2, "le tirage doit privilégier les questions fraîches"


@pytest.mark.asyncio
async def test_un_vivier_vide_ne_casse_rien(db: AsyncSession):
    job = await _offre(db)
    assert await svc.recommend_questions(db, job.id) == []


@pytest.mark.asyncio
async def test_le_rapport_de_couverture_signale_les_manques(db: AsyncSession):
    job = await _offre(db, skills=["Angular", "Java", "SQL"])
    questions = await _vivier(db, job, n=4, skills=["angular"])
    rapport = svc.coverage_report(questions, job.required_skills)
    assert rapport["competences_couvertes"] == ["angular"]
    assert set(rapport["competences_manquantes"]) == {"java", "sql"}


# ── Session ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ouvrir_une_session_fige_lordre(db: AsyncSession):
    job = await _offre(db)
    questions = await _vivier(db, job, n=12)
    application = await _candidature(db, job)

    session = await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()

    assert session.token and len(session.token) >= 32
    assert session.status == SessionStatus.ENVOYE
    assert session.question_count == 12
    reponses = (await db.execute(
        select(TestAnswer).where(TestAnswer.session_id == session.id)
        .order_by(TestAnswer.position)
    )).scalars().all()
    assert [r.position for r in reponses] == list(range(1, 13))
    assert all(r.outcome == AnswerOutcome.NON_ATTEINTE for r in reponses)


@pytest.mark.asyncio
async def test_une_seule_session_active_par_candidature(db: AsyncSession):
    job = await _offre(db)
    questions = await _vivier(db, job, n=4)
    application = await _candidature(db, job)
    await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await svc.create_session(db, application.id, [q.id for q in questions])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_une_question_non_active_ne_part_pas(db: AsyncSession):
    """Une question jamais relue ne doit jamais atteindre un candidat."""
    job = await _offre(db)
    q = await svc.create_question(db, job.id, _qcm(), generated_by="llm:gemini")
    await db.commit()
    application = await _candidature(db, job)

    with pytest.raises(HTTPException) as exc:
        await svc.create_session(db, application.id, [q.id])
    assert exc.value.status_code == 400


# ── Correction ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correction_qcm_unique(db: AsyncSession):
    job = await _offre(db)
    q = await svc.create_question(db, job.id, _qcm(correct="B"))
    await db.commit()
    assert svc.grade(q, ["B"]) == AnswerOutcome.CORRECTE
    assert svc.grade(q, ["A"]) == AnswerOutcome.FAUSSE
    assert svc.grade(q, None) == AnswerOutcome.PASSEE
    assert svc.grade(q, []) == AnswerOutcome.PASSEE


@pytest.mark.asyncio
async def test_correction_qcm_multiple_en_tout_ou_rien(db: AsyncSession):
    """Une réponse partielle n'est pas une demi-compréhension."""
    job = await _offre(db)
    q = await svc.create_question(db, job.id, {
        **_qcm(), "kind": QuestionKind.QCM_MULTIPLE, "correct_answer": ["A", "C"],
    })
    await db.commit()
    assert svc.grade(q, ["A", "C"]) == AnswerOutcome.CORRECTE
    assert svc.grade(q, ["C", "A"]) == AnswerOutcome.CORRECTE   # ordre indifférent
    assert svc.grade(q, ["A"]) == AnswerOutcome.FAUSSE
    assert svc.grade(q, ["A", "C", "D"]) == AnswerOutcome.FAUSSE


@pytest.mark.asyncio
async def test_correction_reponse_courte_tolere_casse_et_accents(db: AsyncSession):
    job = await _offre(db)
    q = await svc.create_question(db, job.id, {
        "statement": "Quelle commande annule le dernier commit ?",
        "options": [], "correct_answer": ["git reset"],
        "kind": QuestionKind.REPONSE_COURTE, "difficulty": QuestionDifficulty.MOYENNE,
    })
    await db.commit()
    assert svc.grade(q, ["  GIT   RESET "]) == AnswerOutcome.CORRECTE
    assert svc.grade(q, ["git revert"]) == AnswerOutcome.FAUSSE


@pytest.mark.asyncio
async def test_le_depassement_se_mesure_contre_le_budget(db: AsyncSession):
    job = await _offre(db)
    questions = await _vivier(db, job, n=3)
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()

    reponse = (await db.execute(
        select(TestAnswer).options(
            __import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(TestAnswer.question)
        ).where(TestAnswer.session_id == session.id, TestAnswer.position == 1)
    )).scalar_one()

    budget = reponse.question.expected_seconds
    reponse.served_at = utcnow()
    svc.record_answer(reponse, ["A"], answered_at=reponse.served_at + timedelta(seconds=budget + 25))
    assert reponse.overrun_seconds == 25

    reponse.served_at = utcnow()
    svc.record_answer(reponse, ["A"], answered_at=reponse.served_at + timedelta(seconds=budget - 10))
    assert reponse.overrun_seconds == 0


# ── Notation — la vérification du lot ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_parcours_complet_donne_une_note_juste(db: AsyncSession):
    """
    Vérification du lot 1 : créer des questions, tirer un test, répondre,
    obtenir une note juste. 12 questions, 9 bonnes → 75/100.
    """
    from sqlalchemy.orm import selectinload

    job = await _offre(db)
    questions = await _vivier(db, job, n=12)
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()

    session = await svc.get_session_by_token(db, session.token)
    maintenant = utcnow()
    for reponse in session.answers:
        reponse.served_at = maintenant
        bonne = reponse.question.correct_answer[0]
        if reponse.position <= 9:
            donne = [bonne]                                   # 9 justes
        elif reponse.position <= 11:
            donne = ["A" if bonne != "A" else "C"]            # 2 fausses
        else:
            donne = None                                      # 1 passée
        svc.record_answer(reponse, donne, answered_at=maintenant + timedelta(seconds=30))

    await svc.score_session(db, session)
    await db.commit()

    assert session.correct_count == 9
    assert session.score == 75.0
    assert session.status == SessionStatus.TERMINE
    issues = [r.outcome for r in session.answers]
    assert issues.count(AnswerOutcome.CORRECTE) == 9
    assert issues.count(AnswerOutcome.FAUSSE) == 2
    assert issues.count(AnswerOutcome.PASSEE) == 1


@pytest.mark.asyncio
async def test_passee_vaut_zero_mais_reste_distinguable(db: AsyncSession):
    """
    Au barème, PASSEE vaut FAUSSE. À la relecture, elles ne disent pas la même
    chose du candidat — et c'est toute la raison des quatre issues.
    """
    job = await _offre(db)
    questions = await _vivier(db, job, n=4)
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()
    session = await svc.get_session_by_token(db, session.token)

    maintenant = utcnow()
    for reponse in session.answers:
        reponse.served_at = maintenant
        donne = None if reponse.position <= 2 else [reponse.question.correct_answer[0]]
        svc.record_answer(reponse, donne, answered_at=maintenant + timedelta(seconds=20))

    await svc.score_session(db, session)
    await db.commit()

    assert session.score == 50.0
    assert sum(1 for r in session.answers if r.outcome == AnswerOutcome.PASSEE) == 2
    assert sum(1 for r in session.answers if r.outcome == AnswerOutcome.FAUSSE) == 0


@pytest.mark.asyncio
async def test_les_statistiques_du_vivier_se_mettent_a_jour(db: AsyncSession):
    """Ces compteurs diront plus tard quelles questions ne discriminent rien."""
    job = await _offre(db)
    questions = await _vivier(db, job, n=3)
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id, [q.id for q in questions])
    await db.commit()
    session = await svc.get_session_by_token(db, session.token)

    maintenant = utcnow()
    for reponse in session.answers:
        reponse.served_at = maintenant
        svc.record_answer(reponse, [reponse.question.correct_answer[0]],
                          answered_at=maintenant + timedelta(seconds=20))
    await svc.score_session(db, session)
    await db.commit()

    for q in questions:
        await db.refresh(q)
        assert q.times_served == 1
        assert q.times_correct == 1
        assert q.success_rate == 100.0


@pytest.mark.asyncio
async def test_une_reponse_juste_et_tres_rapide_est_signalee(db: AsyncSession):
    """Drapeau remonté au RH — jamais une pénalité sur la note."""
    job = await _offre(db)
    q = await svc.create_question(db, job.id, _qcm(difficulty=QuestionDifficulty.DIFFICILE))
    q.status = QuestionStatus.ACTIVE
    await db.commit()
    application = await _candidature(db, job)
    session = await svc.create_session(db, application.id, [q.id])
    await db.commit()
    session = await svc.get_session_by_token(db, session.token)

    reponse = session.answers[0]
    reponse.served_at = utcnow()
    svc.record_answer(reponse, [q.correct_answer[0]],
                      answered_at=reponse.served_at + timedelta(seconds=4))
    await svc.score_session(db, session)
    await db.commit()

    assert session.score == 100.0, "la note ne doit pas être pénalisée"
    assert len(session.anomaly_flags) == 1
    assert session.anomaly_flags[0]["type"] == "reponse_rapide"
