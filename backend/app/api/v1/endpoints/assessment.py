"""
Test technique — routes publiques (candidat) et back-office (RH).

Le partage est net :

* `/assessment/public/{token}/…` n'exige aucun compte et ne renvoie jamais de
  bonne réponse, d'explication ni de note. Un candidat qui inspecte les
  requêtes de son navigateur n'y trouve rien d'exploitable.
* Tout le reste est réservé à `ADMIN` et `RH` — vivier, préparation du
  test, résultats et détail des réponses.
"""
from typing import Annotated
from uuid import UUID
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.assessment import (
    AnswerOutcome, QuestionStatus, SessionStatus, TestAnswer, TestSession,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User
from app.models.scoring import CandidateScore
from app.schemas.candidate_feedback import (
    CandidateVisibilityState, CandidateVisibilityUpdate,
)
from app.schemas.assessment import (
    AnswerReview, BankCoverage, PublicQuestion, PublicTestIntro, PublicTestResult,
    QuestionCreate, QuestionResponse, QuestionUpdate, SendTestRequest,
    SkillBreakdown, SubmitAnswerRequest, SubmitAnswerResponse, TestPreparation,
    TestSessionDetail, TestSessionSummary,
    CandidateEvaluation, CompositeScore, InterviewNotesRequest,
    InterviewScoreRequest, InterviewSuggestion,
)
from app.services.assessment_service import assessment_service
from app.models.application_status import ApplicationStatus

logger = logging.getLogger(__name__)
router = APIRouter()

_RH = require("assessment", "write")


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC — le candidat, par jeton
# ══════════════════════════════════════════════════════════════════════════════

def _vue_candidat(session: TestSession, reponse: TestAnswer) -> PublicQuestion:
    """Question amputée de tout ce qui renseignerait sur la réponse attendue."""
    return PublicQuestion(
        position=reponse.position,
        total=session.question_count,
        statement=reponse.question.statement,
        options=list(reponse.question.options or []),
        kind=reponse.question.kind,
        seconds_remaining=assessment_service.seconds_remaining(session),
    )


@router.get("/public/{token}", response_model=PublicTestIntro)
async def test_intro(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Écran d'accueil : ce qui est annoncé au candidat avant de commencer.

    N'ouvre pas le test et ne démarre pas le chronomètre — c'est `start` qui
    le fait, quand le candidat clique en connaissance de cause.
    """
    session = await assessment_service.get_session_by_token(db, token)
    titre = (await db.execute(
        select(JobOffer.title)
        .join(Application, Application.job_offer_id == JobOffer.id)
        .where(Application.id == session.application_id)
    )).scalar_one_or_none()

    from app.utils.helpers import as_utc, utcnow
    return PublicTestIntro(
        job_title=titre or "Poste",
        question_count=session.question_count,
        duration_minutes=session.duration_minutes,
        status=session.status,
        already_submitted=session.status in (SessionStatus.TERMINE, SessionStatus.EXPIRE),
        link_expired=(session.status == SessionStatus.ENVOYE
                      and utcnow() > as_utc(session.link_expires_at)),
    )


@router.post("/public/{token}/start", response_model=SubmitAnswerResponse)
async def start_test(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Démarre le chronomètre et sert la première question."""
    session = await assessment_service.open_session(db, token)
    if session.status in (SessionStatus.TERMINE, SessionStatus.EXPIRE):
        await db.commit()
        return SubmitAnswerResponse(accepted=False, next_question=None, finished=True)

    reponse = await assessment_service.serve_next(db, session)
    await db.commit()
    if reponse is None:
        return SubmitAnswerResponse(accepted=False, next_question=None, finished=True)
    return SubmitAnswerResponse(
        accepted=True, next_question=_vue_candidat(session, reponse), finished=False,
    )


@router.post("/public/{token}/answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    token: str,
    body: SubmitAnswerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Enregistre une réponse — ou un « Passer », qui compte comme une erreur —
    puis sert la question suivante.

    La réponse ne dit jamais si le candidat a eu juste : l'apprendre question
    après question reviendrait à lui livrer le vivier.
    """
    session = await assessment_service.get_session_by_token(db, token)
    suivante = await assessment_service.submit_answer(db, session, body.position, body.answer)
    await db.commit()

    if suivante is None:
        return SubmitAnswerResponse(accepted=True, next_question=None, finished=True)
    return SubmitAnswerResponse(
        accepted=True, next_question=_vue_candidat(session, suivante), finished=False,
    )


@router.post("/public/{token}/finish", response_model=PublicTestResult)
async def finish_test(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Clôt le test. Les questions non atteintes restent NON_ATTEINTE et valent
    zéro, comme une réponse fausse, mais restent distinguables à la relecture.
    """
    session = await assessment_service.get_session_by_token(db, token)
    if session.status == SessionStatus.EN_COURS:
        await assessment_service.score_session(db, session)
        await db.commit()
    return PublicTestResult(
        finished=True,
        message="Vos réponses ont été transmises au recruteur.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  BACK-OFFICE — vivier
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/jobs/{job_id}/questions", response_model=list[QuestionResponse],
            dependencies=[Depends(_RH)])
async def list_bank(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: QuestionStatus | None = Query(default=None, alias="status"),
):
    return await assessment_service.list_questions(
        db, job_id, [status_filter] if status_filter else None
    )


@router.post("/jobs/{job_id}/questions", response_model=QuestionResponse,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(_RH)])
async def create_question(
    job_id: UUID, body: QuestionCreate, db: Annotated[AsyncSession, Depends(get_db)],
):
    question = await assessment_service.create_question(db, job_id, body.model_dump())
    await db.commit()
    await db.refresh(question)
    return question


@router.patch("/questions/{question_id}", response_model=QuestionResponse,
              dependencies=[Depends(_RH)])
async def update_question(
    question_id: UUID, body: QuestionUpdate, db: Annotated[AsyncSession, Depends(get_db)],
):
    question = await assessment_service.update_question(
        db, question_id, body.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(question)
    return question


@router.post("/questions/{question_id}/status", response_model=QuestionResponse,
             dependencies=[Depends(_RH)])
async def set_question_status(
    question_id: UUID,
    new_status: QuestionStatus,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    question = await assessment_service.set_question_status(
        db, question_id, new_status, validated_by=current_user.id
    )
    await db.commit()
    await db.refresh(question)
    return question


@router.post("/jobs/{job_id}/questions/generate", dependencies=[Depends(_RH)])
async def generate_bank(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(default=30, ge=5, le=60),
):
    """
    Génère le vivier d'une offre.

    Les questions naissent GENEREE : elles n'atteindront un candidat qu'après
    relecture. Le compte rendu inclut le nombre d'écartées et la raison de
    chaque rejet — c'est cette mesure, et non le nombre de questions produites,
    qui dit si le prompt tient.
    """
    from app.agents.question_generator_agent import question_generator_agent

    rapport = await question_generator_agent.run(db, job_id, count=count)
    await db.commit()
    return rapport


@router.post("/jobs/{job_id}/questions/activate", dependencies=[Depends(_RH)])
async def activate_bank(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bascule en ACTIVE toutes les questions relues. Elles deviennent tirables."""
    n = await assessment_service.activate_bank(db, job_id, current_user.id)
    await db.commit()
    return {"activated": n}


# ══════════════════════════════════════════════════════════════════════════════
#  BACK-OFFICE — préparation et envoi
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/applications/{app_id}/prepare", response_model=TestPreparation,
            dependencies=[Depends(_RH)])
async def prepare_test(
    app_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(default=12, ge=1, le=40),
):
    """
    Présélectionne les questions du test et rend l'état de la couverture.

    Le RH voit les 12 proposées, les compteurs de difficulté et les compétences
    non couvertes. Il ajuste, puis confirme.
    """
    application = (await db.execute(
        select(Application).where(Application.id == app_id)
    )).scalar_one_or_none()
    if not application:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable.")

    offre = (await db.execute(
        select(JobOffer).where(JobOffer.id == application.job_offer_id)
    )).scalar_one()

    questions = await assessment_service.recommend_questions(db, offre.id, count)
    coverage = assessment_service.coverage_report(questions, offre.required_skills or [])
    return TestPreparation(
        questions=[QuestionResponse.model_validate(q) for q in questions],
        coverage=BankCoverage(**coverage),
    )


@router.post("/applications/{app_id}/send", response_model=TestSessionSummary,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(_RH)])
async def send_test(
    app_id: UUID,
    body: SendTestRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Ouvre la session et envoie le lien au candidat."""
    session = await assessment_service.create_session(
        db, app_id, body.question_ids, duration_minutes=body.duration_minutes
    )
    # Qui a envoyé : l'alerte de fin s'adressera à cette personne plutôt qu'à
    # tous les administrateurs, où elle se noierait.
    session.sent_by = current_user.id
    application = (await db.execute(
        select(Application).where(Application.id == app_id)
    )).scalar_one()
    application.status = ApplicationStatus.TEST_SENT.value
    await db.commit()
    await db.refresh(session)

    destinataire = (await db.execute(
        select(User.email, Candidate.full_name, JobOffer.title)
        .select_from(Application)
        .join(Candidate, Application.candidate_id == Candidate.id)
        .join(User, Candidate.user_id == User.id)
        .join(JobOffer, Application.job_offer_id == JobOffer.id)
        .where(Application.id == app_id)
    )).first()

    if destinataire:
        from app.services.email_service import send_technical_test_invitation
        background_tasks.add_task(
            send_technical_test_invitation,
            to_email=destinataire[0], candidate_name=destinataire[1],
            job_title=destinataire[2], token=session.token,
            question_count=session.question_count,
            duration_minutes=session.duration_minutes,
            expires_at=session.link_expires_at,
        )
    logger.info("Test envoyé pour la candidature %s (session %s)", app_id, session.id)
    return session


# ══════════════════════════════════════════════════════════════════════════════
#  BACK-OFFICE — résultats
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/applications/{app_id}/session", response_model=TestSessionDetail,
            dependencies=[Depends(_RH)])
async def test_detail(app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Détail des réponses — le cœur de la relecture.

    Une ligne par question avec la réponse donnée, la bonne réponse et l'issue,
    plus deux totaux : la répartition des issues et la réussite PAR COMPÉTENCE.
    C'est cette seconde vue qui sert à préparer l'entretien.
    """
    session = (await db.execute(
        select(TestSession)
        .options(selectinload(TestSession.answers).selectinload(TestAnswer.question))
        .where(TestSession.application_id == app_id)
        .order_by(TestSession.created_at.desc())
    )).scalars().first()
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun test pour cette candidature.")

    reponses = sorted(session.answers, key=lambda r: r.position)

    issues: dict[str, int] = {o.value: 0 for o in AnswerOutcome}
    par_competence: dict[str, dict] = {}
    for r in reponses:
        issues[r.outcome.value] += 1
        tag = (r.question.skill_tag or "non rattachée").strip().lower()
        stat = par_competence.setdefault(tag, {"asked": 0, "correct": 0})
        stat["asked"] += 1
        if r.outcome == AnswerOutcome.CORRECTE:
            stat["correct"] += 1

    return TestSessionDetail(
        **TestSessionSummary.model_validate(session).model_dump(),
        outcome_counts=issues,
        by_skill=[
            SkillBreakdown(
                skill=tag, asked=s["asked"], correct=s["correct"],
                rate=round(s["correct"] / s["asked"] * 100, 1) if s["asked"] else 0.0,
            )
            for tag, s in sorted(par_competence.items())
        ],
        answers=[
            AnswerReview(
                position=r.position,
                statement=r.question.statement,
                options=list(r.question.options or []),
                given_answer=r.given_answer,
                correct_answer=list(r.question.correct_answer or []),
                outcome=r.outcome,
                difficulty=r.question.difficulty,
                skill_tag=r.question.skill_tag,
                elapsed_seconds=r.elapsed_seconds,
                expected_seconds=r.question.expected_seconds,
                overrun_seconds=r.overrun_seconds,
            )
            for r in reponses
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  BACK-OFFICE — ce que le candidat a le droit de voir
# ══════════════════════════════════════════════════════════════════════════════

async def _score_de(db: AsyncSession, app_id: UUID) -> CandidateScore:
    score = (await db.execute(
        select(CandidateScore).where(CandidateScore.application_id == app_id)
    )).scalar_one_or_none()
    if not score:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Aucune évaluation pour cette candidature.")
    return score


@router.get("/applications/{app_id}/visibility",
            response_model=CandidateVisibilityState, dependencies=[Depends(_RH)])
async def get_candidate_visibility(
    app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)],
):
    """Ce que le candidat voit aujourd'hui de son évaluation."""
    score = await _score_de(db, app_id)
    return CandidateVisibilityState(
        application_id=app_id,
        test_score_visible=score.test_score_visible,
        interview_feedback_visible=score.interview_feedback_visible,
        candidate_feedback=score.candidate_feedback,
        has_test_score=score.test_score is not None,
    )


@router.post("/applications/{app_id}/visibility",
             response_model=CandidateVisibilityState, dependencies=[Depends(_RH)])
async def set_candidate_visibility(
    app_id: UUID,
    body: CandidateVisibilityUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Ouvre ou referme ce que le candidat voit.

    Fermé par défaut, et refermable à tout moment. Le RH décide candidature par
    candidature : partager la note d'un test réussi n'engage pas à partager
    celle d'un test raté, et l'inverse non plus.

    Le retour d'entretien partagé est un champ SÉPARÉ des notes internes. Des
    observations prises pour soi pendant un entretien ne se relisent pas comme
    un message adressé à quelqu'un ; les confondre reviendrait à publier des
    notes que personne n'a écrites dans cette intention.
    """
    score = await _score_de(db, app_id)

    if body.test_score_visible is not None:
        score.test_score_visible = body.test_score_visible
    if body.interview_feedback_visible is not None:
        score.interview_feedback_visible = body.interview_feedback_visible
    if body.candidate_feedback is not None:
        texte = body.candidate_feedback.strip()
        score.candidate_feedback = texte or None

    # Ouvrir le partage d'un retour qui n'existe pas ne montrerait rien : on le
    # referme plutôt que de laisser un drapeau levé sur du vide.
    if score.interview_feedback_visible and not score.candidate_feedback:
        score.interview_feedback_visible = False

    await db.commit()
    await db.refresh(score)
    logger.info("Visibilité candidat mise à jour pour la candidature %s", app_id)
    return CandidateVisibilityState(
        application_id=app_id,
        test_score_visible=score.test_score_visible,
        interview_feedback_visible=score.interview_feedback_visible,
        candidate_feedback=score.candidate_feedback,
        has_test_score=score.test_score is not None,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  BACK-OFFICE — évaluation d'entretien et score composite
# ══════════════════════════════════════════════════════════════════════════════

async def _evaluation(db: AsyncSession, app_id: UUID) -> CandidateEvaluation:
    """Vue d'ensemble, recalculée à la volée pour ne jamais afficher un composite périmé."""
    from app.services.composite_score_service import composite_score_service
    from app.services.interview_evaluation_service import interview_evaluation_service

    score = await interview_evaluation_service.get_or_create_score(db, app_id)
    await composite_score_service.refresh(db, app_id)
    composite = composite_score_service.compute(
        cv_score=score.total_score,
        test_score=score.test_score,
        interview_score=score.interview_score,
    )
    return CandidateEvaluation(
        application_id=app_id,
        cv_score=score.total_score,
        test_score=score.test_score,
        interview_score=score.interview_score,
        interview_notes=score.interview_notes,
        interview_ai_suggestion=score.interview_ai_suggestion,
        composite=CompositeScore(**composite),
    )


@router.get("/applications/{app_id}/evaluation", response_model=CandidateEvaluation,
            dependencies=[Depends(_RH)])
async def get_evaluation(app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """Les trois volets et leur composition. Réservé au RH et à l'admin."""
    evaluation = await _evaluation(db, app_id)
    await db.commit()
    return evaluation


@router.post("/applications/{app_id}/interview/notes", response_model=CandidateEvaluation,
             dependencies=[Depends(_RH)])
async def save_interview_notes(
    app_id: UUID, body: InterviewNotesRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Enregistre les notes libres du RH, sans rien noter."""
    from app.services.interview_evaluation_service import interview_evaluation_service
    from app.services.interview_service import interview_service

    await interview_service.verifier_droit_evaluation(db, app_id, current_user)

    await interview_evaluation_service.save_notes(db, app_id, body.notes)
    evaluation = await _evaluation(db, app_id)
    await db.commit()
    return evaluation


@router.post("/applications/{app_id}/interview/suggest", response_model=InterviewSuggestion,
             dependencies=[Depends(_RH)])
async def suggest_interview_evaluation(
    app_id: UUID, body: InterviewNotesRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Propose une évaluation par critère à partir des notes du RH.

    La proposition est enregistrée À PART de la note retenue : elle ne devient
    jamais la décision. Le RH la reprend, la modifie, ou l'ignore.
    """
    from app.services.interview_evaluation_service import interview_evaluation_service
    from app.services.interview_service import interview_service

    await interview_service.verifier_droit_evaluation(db, app_id, current_user)
    proposition = await interview_evaluation_service.suggest(db, app_id, body.notes)
    await db.commit()
    return InterviewSuggestion(**proposition)


@router.post("/applications/{app_id}/interview/score", response_model=CandidateEvaluation,
             dependencies=[Depends(_RH)])
async def set_interview_score(
    app_id: UUID, body: InterviewScoreRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Fixe la note d'entretien — la décision du recruteur, celle qui compte."""
    from app.services.interview_evaluation_service import interview_evaluation_service
    from app.services.interview_service import interview_service

    await interview_service.verifier_droit_evaluation(db, app_id, current_user)
    await interview_evaluation_service.set_score(
        db, app_id, body.interview_score, notes=body.notes
    )
    # L'entretien passe dans « Évalués » (ou en ressort si la note est effacée).
    await interview_service.marquer_evaluation(
        db, app_id, current_user, evalue=body.interview_score is not None
    )
    evaluation = await _evaluation(db, app_id)
    await db.commit()
    return evaluation
