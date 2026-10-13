from typing import Annotated
from uuid import UUID

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.core.rbac import require
from app.db.session import get_db
from app.models import application_status as statuts
from app.models.recruitment import Application
from app.models.user import User
from app.schemas.decision import (
    ApplyDecisionRequest, ApplyDecisionResponse,
    CompositeView, CvSignals, EvaluateOfferRequest, EvaluateOfferResponse,
    HiringRecommendation, InterviewSignals, JobRecommendations, TestSignals, TieBreak,
)
from app.services.decision_service import get_decision_service
from app.services.hiring_decision_service import SCORE_BANDS, load_job_evidence, rank

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(require("decision", "read"))]
)


# ── Salary-offer evaluation (stateless) ─────────────────────────────────────

@router.post("/evaluate-offer", dependencies=[Depends(require("decision", "write"))], response_model=EvaluateOfferResponse)
async def evaluate_offer(body: EvaluateOfferRequest):
    """Evaluate a salary offer against a predicted salary (accept / counter / reject)."""
    service = get_decision_service()
    decision, reason, counter = service.evaluate_offer(
        body.predicted_salary, body.offered_salary, body.confidence
    )
    return EvaluateOfferResponse(
        decision=decision.value, reason=reason, counter_offer=counter
    )


# ── Hiring recommendation (CV + test + entretien) ──────────────────────────

def _to_schema(item: dict) -> HiringRecommendation:
    e, a = item["evidence"], item["analysis"]
    c = a["composite"]
    return HiringRecommendation(
        application_id=e.application_id,
        candidate_id=e.candidate_id,
        candidate_name=e.candidate_name,
        decision_rank=item["decision_rank"],
        recommendation=a["recommendation"],
        confidence=a["confidence"],
        rationale=a["rationale"],
        strengths=a["strengths"],
        warnings=a["warnings"],
        next_step=a["next_step"],
        explanation=a["explanation"],
        composite=CompositeView(
            score=c["score"], completeness=c["completeness"],
            available=c["available"], missing=c["missing"], band=c["band"],
        ),
        cv=CvSignals(
            score=e.cv_score, skills_score=e.skills_score,
            experience_score=e.experience_score, education_score=e.education_score,
            matched_skills=e.matched_skills, missing_skills=e.missing_skills,
        ),
        test=TestSignals(
            status=e.test_status, score=e.test_score,
            hard_success_rate=e.hard_success_rate, hard_total=e.hard_total,
            anomaly_count=e.anomaly_count, overrun_questions=e.overrun_questions,
        ),
        interview=InterviewSignals(
            score=e.interview_score, status=e.interview_status,
            has_notes=e.has_interview_notes,
        ),
        expected_salary=e.expected_salary,
        tie=TieBreak(**item["tie"]) if item["tie"] else None,
        total_score=e.cv_score,
        application_status=e.application_status,
    )


@router.get("/jobs/{job_id}/recommendations", response_model=JobRecommendations)
async def job_recommendations(job_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Recommandation de chaque candidature ouverte d'une offre, classées et
    départagées : CV, test technique et entretien réunis (voir
    `hiring_decision_service`). Les ex æquo reçoivent le critère qui les sépare.
    """
    evidences = await load_job_evidence(db, job_id)
    return JobRecommendations(
        job_offer_id=job_id,
        bands=SCORE_BANDS,
        candidates=[_to_schema(item) for item in rank(evidences)],
    )


@router.get("/applications/{app_id}/recommendation", response_model=HiringRecommendation)
async def hiring_recommendation(app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Recommandation d'une seule candidature. Calculée DANS le contexte de son
    offre : le rang et le départage n'ont de sens que face aux autres candidats.
    """
    app = (await db.execute(select(Application).where(Application.id == app_id))).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    for item in rank(await load_job_evidence(db, app.job_offer_id)):
        if item["evidence"].application_id == app_id:
            return _to_schema(item)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Aucun score pour cette candidature (CV non analysé, ou candidature close).",
    )


# ── Appliquer la recommandation ─────────────────────────────────────────────

@router.post(
    "/applications/{app_id}/apply",
    response_model=ApplyDecisionResponse,
    dependencies=[Depends(require("decision", "write"))],
)
async def apply_decision(
    app_id: UUID,
    body: ApplyDecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    La recommandation devient le statut de la candidature : Recruter →
    Acceptée, Rejeter → Rejetée (e-mail de refus), En réserve → En réserve
    (e-mail « candidature conservée » et entrée au vivier, qui l'invitera
    ensuite sur les offres proches de son profil).

    Réservé à qui décide (`decision:write`, RH et administrateur).
    """
    from app.services.email_service import send_rejection_email, send_talent_pool_notice
    from app.services.notification_service import notification_service
    from app.services.talent_pool_service import appliquer_decision

    fait = await appliquer_decision(db, app_id, body.decision, current_user)
    await db.commit()

    libelle = statuts.label(fait.statut)
    email = False
    if body.decision == "REJECT":
        background_tasks.add_task(send_rejection_email, fait.user.email, fait.candidate.full_name,
                                  fait.job.title, body.message.strip())
        email = True
    elif body.decision == "HOLD":
        background_tasks.add_task(send_talent_pool_notice, to_email=fait.user.email,
                                  candidate_name=fait.candidate.full_name, job_title=fait.job.title)
        email = True

    await notification_service.notify_user(
        db, recipient_id=fait.user.id, type="APPLICATION_STATUS_CHANGED",
        title="Mise à jour de votre candidature",
        message=f"Votre candidature pour « {fait.job.title} » est maintenant : {libelle}.",
        link="/frontoffice/applications",
    )
    await notification_service.notify_admins(
        db, actor=current_user, type="APPLICATION_STATUS_CHANGED",
        title="Décision appliquée",
        message=(f"{current_user.full_name or current_user.username} a appliqué la décision "
                 f"« {libelle} » à {fait.candidate.full_name} ({fait.job.title})."),
        link="/admin/decision",
    )
    await db.commit()

    logger.info("Décision %s appliquée à la candidature %s.", body.decision, app_id)
    return ApplyDecisionResponse(application_id=app_id, application_status=fait.statut, email_sent=email)
