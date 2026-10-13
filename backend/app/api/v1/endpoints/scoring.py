from typing import Annotated
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, status, HTTPException, BackgroundTasks
import logging

from app.core.rbac import require
from app.db.session import get_db
from app.models.recruitment import JobOffer, Application, Candidate
from app.schemas.scoring import (
    CVAnalysisResponse,
    CandidateScoreResponse,
    JobRankingResponse,
    CandidateRankingItem,
    AnalysisStartedResponse,
    BulkAnalysisResponse,
)
from app.agents.scoring_agent import scoring_agent
from app.services.scoring_service import scoring_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/applications/{app_id}/analyze",
    response_model=AnalysisStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("scoring", "write"))],
)
async def analyze_application(
    app_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    """Trigger CV analysis and scoring for a single application (async)."""
    try:
        # Verify application exists
        app_result = await db.execute(
            select(Application).where(Application.id == app_id)
        )
        app = app_result.scalar_one_or_none()
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )

        logger.info(f"Queuing CV analysis for application {app_id}")
        background_tasks.add_task(scoring_agent.run_analysis_task, app_id)
        return AnalysisStartedResponse(
            message="Analysis started",
            application_id=app_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting analysis: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error starting analysis"
        )


@router.post(
    "/jobs/{job_id}/analyze-all",
    response_model=BulkAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require("scoring", "write"))],
)
async def analyze_all_for_job(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
):
    """Trigger CV analysis and scoring for all applications of a job (async)."""
    try:
        # Verify job exists and get application count
        job_result = await db.execute(select(JobOffer).where(JobOffer.id == job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job offer not found",
            )

        # Count applications for this job
        app_count = await db.scalar(
            select(func.count(Application.id)).where(Application.job_offer_id == job_id)
        ) or 0

        logger.info(f"Queuing bulk analysis for job {job_id} with {app_count} applications")
        background_tasks.add_task(scoring_agent.run_bulk_analysis_task, job_id)
        return BulkAnalysisResponse(
            message="Bulk analysis started",
            job_id=job_id,
            count_queued=app_count,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting bulk analysis: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error starting bulk analysis"
        )


@router.get(
    "/applications/{app_id}/analysis",
    response_model=CVAnalysisResponse,
    dependencies=[Depends(require("scoring", "read"))],
)
async def get_cv_analysis(
    app_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get extracted CV data for an application (Admin/HR only)."""
    try:
        analysis = await scoring_service.get_analysis_by_application(db, app_id)
        if not analysis:
            logger.warning(f"CV analysis not found for application {app_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CV analysis not found. Try triggering analysis with POST /analyze",
            )
        logger.info(f"Retrieved CV analysis for application {app_id}")
        return analysis
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving CV analysis: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving CV analysis"
        )


@router.get(
    "/applications/{app_id}/score",
    response_model=CandidateScoreResponse,
    dependencies=[Depends(require("scoring", "read"))],
)
async def get_candidate_score(
    app_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get score for a candidate's application (Admin/HR only)."""
    try:
        # Verify application exists first
        app_result = await db.execute(
            select(Application).where(Application.id == app_id)
        )
        if not app_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found",
            )

        score = await scoring_service.get_score_by_application(db, app_id)
        if not score:
            logger.warning(f"Score not found for application {app_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Candidate score not found. Try triggering analysis with POST /analyze",
            )
        logger.info(f"Retrieved score for application {app_id}: {score.total_score}")
        return score
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving candidate score: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving candidate score"
        )


@router.get(
    "/jobs/{job_id}/ranking",
    response_model=JobRankingResponse,
    dependencies=[Depends(require("scoring", "read"))],
)
async def get_job_ranking(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get ranked candidates for a job offer."""
    try:
        # Verify job exists
        job_result = await db.execute(select(JobOffer).where(JobOffer.id == job_id))
        job = job_result.scalar_one_or_none()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job offer not found",
            )

        scores = await scoring_service.get_scores_by_job(db, job_id)

        if not scores:
            logger.info(f"No scores found for job {job_id}. Candidates may not have been analyzed yet.")
            return JobRankingResponse(
                job_offer_id=job_id,
                total_candidates=0,
                ranking=[],
            )

        # Bulk-fetch active invitations for these applications so we can
        # tell the UI which candidates already have a scheduled interview.
        from app.models.interview import InterviewInvitation, InvitationStatus
        from app.services.interview_service import entretien_termine
        app_ids = [s.application_id for s in scores]
        from sqlalchemy.orm import selectinload
        inv_result = await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(
                InterviewInvitation.application_id.in_(app_ids),
                InterviewInvitation.status.in_(
                    [InvitationStatus.PENDING, InvitationStatus.CONFIRMED]
                ),
            )
        )
        inv_by_app: dict = {}
        for inv in inv_result.scalars().all():
            current = inv_by_app.get(inv.application_id)
            # La plus RÉCENTE. Après un entretien passé, une nouvelle invitation
            # peut coexister avec l'ancienne, restée CONFIRMED : c'est la
            # nouvelle que le RH doit voir, pas l'entretien déjà tenu.
            if current is None or inv.created_at > current.created_at:
                inv_by_app[inv.application_id] = inv

        # État du test technique, en UNE requête pour tout le classement —
        # comme pour les invitations ci-dessus. Une session par candidature au
        # plus est active, mais l'historique peut en contenir plusieurs : on
        # garde la plus récente, qui est celle que le RH regarde.
        from app.models.assessment import TestSession
        sess_result = await db.execute(
            select(TestSession)
            .where(TestSession.application_id.in_(app_ids))
            .order_by(TestSession.created_at.asc())
        )
        session_by_app: dict = {}
        for sess in sess_result.scalars().all():
            session_by_app[sess.application_id] = sess   # la dernière écrase

        # Bulk-fetch candidate names so the UI can show "Prénom Nom" instead
        # of the raw candidate_id.
        candidate_ids = [s.candidate_id for s in scores]
        candidates_result = await db.execute(
            select(Candidate).where(Candidate.id.in_(candidate_ids))
        )
        name_by_candidate = {c.id: c.full_name for c in candidates_result.scalars().all()}

        # Prétentions salariales, en une requête plutôt qu'une par ligne.
        from app.models.recruitment import Application as ApplicationModel
        exp_result = await db.execute(
            select(ApplicationModel.id, ApplicationModel.expected_salary)
            .where(ApplicationModel.id.in_(app_ids))
        )
        expected_by_app = {row[0]: row[1] for row in exp_result.all()}

        # L'éligibilité est décidée ici, jamais dans le navigateur.
        from app.core.config import settings
        from app.models.assessment import SessionStatus
        seuil = settings.TEST_ELIGIBILITY_MIN_SCORE
        # Un test déjà ouvert interdit d'en envoyer un second : le service
        # n'autorise qu'une session active par candidature.
        _EN_COURS = (SessionStatus.ENVOYE, SessionStatus.EN_COURS)

        ranking = []
        for score in scores:
            inv = inv_by_app.get(score.application_id)
            sess = session_by_app.get(score.application_id)
            statut_test = sess.status.value if sess else None
            ranking.append(CandidateRankingItem(
                candidate_id=score.candidate_id,
                candidate_name=name_by_candidate.get(score.candidate_id),
                application_id=score.application_id,
                total_score=score.total_score,
                rank=score.rank,
                skills_score=score.skills_score,
                experience_score=score.experience_score,
                education_score=score.education_score,
                score_details=score.score_details,
                interview_status=(inv.status.value if inv and hasattr(inv.status, 'value') else (str(inv.status) if inv else None)),
                interview_invitation_id=(inv.id if inv else None),
                interview_confirmed_at=(inv.confirmed_at if inv else None),
                interview_ended=bool(
                    inv and inv.status == InvitationStatus.CONFIRMED and entretien_termine(inv)
                ),
                expected_salary=expected_by_app.get(score.application_id),
                test_status=statut_test,
                test_score=sess.score if sess else None,
                can_send_test=(
                    score.total_score >= seuil
                    and (sess is None or sess.status not in _EN_COURS)
                ),
                # Vrai quand l'entretien n'a plus de raison d'attendre.
                #
                # Le test informe la décision, il ne la prend pas : l'écran
                # ATTÉNUE le bouton quand c'est faux, il ne le retire pas.
                # Et un candidat sous le seuil ne peut pas passer de test —
                # le lui opposer le bloquerait pour toujours.
                can_schedule_interview=(
                    score.total_score < seuil                     # pas de test possible
                    or (sess is not None and sess.status not in _EN_COURS)
                ),
            ))

        logger.info(f"Retrieved ranking for job {job_id}: {len(scores)} candidates")
        return JobRankingResponse(
            job_offer_id=job_id,
            total_candidates=len(scores),
            ranking=ranking,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving job ranking: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving job ranking"
        )
