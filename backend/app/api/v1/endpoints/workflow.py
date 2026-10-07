import asyncio
from datetime import datetime
from uuid import UUID
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.recruitment import Application, Candidate
from app.models.scoring import CandidateScore
from app.services.email_service import (
    send_interview_invitation_link,
    send_rejection_email,
)
from app.services.interview_service import interview_service, public_url_for
from app.services.notification_service import notification_service
from app.integrations import llm_router
from app.models import application_status
from app.models.application_status import ApplicationStatus
from app.services.candidate_context import (
    get_application_context as _get_application_context,
    get_candidate_profile as _get_candidate_profile,
    candidate_market_bands,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class ScheduleInterviewRequest(BaseModel):
    """
    The frontend sends a list of ISO-8601 datetimes (one per proposed slot).
    Older clients that send plain strings ('2026-05-20 à 10h00') are still
    handled: we'll try to parse them as ISO first, then fall back to passing
    them straight to the email template.
    """
    slots: list[datetime] = Field(
        ..., min_length=1, max_length=5,
        description="ISO-8601 datetimes — one per proposed slot.",
    )
    duration_minutes: int = Field(default=30, ge=10, le=240)
    expires_in_hours: int = Field(default=48, ge=1, le=336)
    message: str = Field(default="", max_length=2000)
    recruiter_id: UUID | None = Field(default=None, description="Ancien champ : un seul membre.")
    recruiter_ids: list[UUID] = Field(
        default_factory=list, max_length=10,
        description="Membres de l'entretien : ceux qui le mènent et pourront l'évaluer.",
    )
    meet_url: str | None = Field(
        default=None, max_length=500,
        description="Lien de visioconférence figé dès la planification. "
                    "Laissé vide, un lien est produit à la confirmation.",
    )


class RejectRequest(BaseModel):
    message: str = Field(default="", max_length=1000)


class StartNegotiationRequest(BaseModel):
    employer_offer: float = Field(..., gt=0, description="Offre salariale initiale (TND)")


class NegotiationAnalysisRequest(BaseModel):
    requested_salary: float = Field(..., gt=0, description="Salaire demandé par le candidat (TND/mois)")
    base_salary: Optional[float] = Field(
        default=None, gt=0,
        description="Minimum du budget du poste (éditable) — salaire min. de l'offre si omis",
    )
    base_salary_max: Optional[float] = Field(
        default=None, gt=0,
        description="Maximum du budget du poste (éditable) — salaire max. de l'offre si omis. "
                    "C'est CE montant qui sert de seuil de dépassement budgétaire.",
    )


class ExplanationLine(BaseModel):
    """Un fait de l'analyse, avec sa tonalité et sa place à l'écran."""
    kind: str = "info"  # "recommendation" | "alert" | "budget" | "profile" | "market"
    tone: str  # "success" | "info" | "warn" | "danger"
    text: str


class NegotiationAnalysisResponse(BaseModel):
    candidate_name: str
    job_title: str
    candidate_experience_years: Optional[float]
    experience_source: str  # "cv" | "candidate_score" | "job_requirement"
    required_experience_years: Optional[float]
    experience_gap_years: Optional[float]
    match_score: Optional[float]
    qualification_score: float

    # ── Marché : une FOURCHETTE, jamais un point ──────────────────────────────
    market_min: float
    market_max: float
    market_reference: float
    market_gap: float
    job_seniority_label: str
    confidence: float

    # ── Budget de l'offre : la seule référence d'acceptation ──────────────────
    budget_min: float
    budget_max: float
    budget_overrun: float
    position_in_range: Optional[float]

    requested_salary: float
    verdict: str  # "acceptable" | "counter_offer" | "stretch" | "negotiation_required"
    decision: str  # "ACCEPT" | "COUNTER" | "NEGOTIATE" | "HIGH_REQUEST"
    negotiation_score: float
    score_breakdown: dict
    signals: list[str]
    is_qualified: bool
    is_exceptional: bool
    recommended_salary: float
    explanation: str
    explanation_lines: list[ExplanationLine]

    # ── Rétro-compatibilité (anciens consommateurs de l'API) ──────────────────
    predicted_salary: float
    predicted_range: list[float]
    base_salary: float


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=4000)


class NegotiationChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class NegotiationChatResponse(BaseModel):
    reply: str
    recommendation: Optional[str] = None  # "accept" | "counter" | "reject" | None
    suggested_amount: Optional[float] = None
    predicted_salary: Optional[float] = None
    source: str  # "llm" | "heuristic"


class WorkflowResponse(BaseModel):
    message: str
    application_id: UUID
    email_sent: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_other_candidates(db: AsyncSession, job_offer_id, exclude_app_id: UUID, limit: int = 5) -> list[dict]:
    """Autres candidats sur la même offre, pour donner au RH (et au chat) une vue budget/comparaison."""
    result = await db.execute(
        select(CandidateScore, Application, Candidate)
        .join(Application, CandidateScore.application_id == Application.id)
        .join(Candidate, CandidateScore.candidate_id == Candidate.id)
        .where(CandidateScore.job_offer_id == job_offer_id, CandidateScore.application_id != exclude_app_id)
        .order_by(CandidateScore.total_score.desc())
        .limit(limit)
    )
    return [
        {
            "candidate_name": candidate.full_name,
            "application_id": str(application.id),
            "status": application.status,
            "match_score": score.total_score,
        }
        for score, application, candidate in result.all()
    ]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/applications/{app_id}/schedule-interview",
    response_model=WorkflowResponse,
)
async def schedule_interview(
    app_id: UUID,
    body: ScheduleInterviewRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Create an interview invitation with proposed slots and send the candidate
    a public link to choose one. Replaces the old free-text email flow.
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.RH, UserRole.RECRUTEUR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    app, candidate, user, job = await _get_application_context(db, app_id)

    # Même règle que le changement de statut : une candidature rejetée, retirée
    # ou déjà recrutée ne repart pas en « entretien planifié ». Sans ce
    # garde-fou, planifier depuis ici contournait `can_transition` et faisait
    # reculer un dossier clos — alors que l'invitation partait quand même.
    if not application_status.can_transition(app.status, ApplicationStatus.INTERVIEW_SCHEDULED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Impossible de planifier un entretien : la candidature est "
                    f"« {application_status.label(app.status)} »."),
        )

    membres = list(body.recruiter_ids)
    if body.recruiter_id:
        membres.append(body.recruiter_id)
    # Un recruteur ne voit que les entretiens dont il est membre : celui qu'il
    # planifie l'inclut, sinon il disparaîtrait de sa liste aussitôt créé.
    if current_user.role == UserRole.RECRUTEUR and current_user.id not in membres:
        membres.append(current_user.id)

    invitation = await interview_service.create_invitation(
        db,
        application_id=app_id,
        slots=body.slots,
        duration_minutes=body.duration_minutes,
        message=body.message,
        expires_in_hours=body.expires_in_hours,
        created_by=current_user.id,
        member_ids=membres,
        meet_url=body.meet_url,
    )

    app.status = ApplicationStatus.INTERVIEW_SCHEDULED.value
    await db.commit()

    background_tasks.add_task(
        send_interview_invitation_link,
        to_email=user.email,
        candidate_name=candidate.full_name,
        job_title=job.title,
        slots=body.slots,
        public_url=public_url_for(invitation.token),
        message=body.message,
        expires_at=invitation.expires_at,
    )

    logger.info(f"Interview invitation {invitation.id} created for application {app_id}, "
                f"email queued to {user.email}, public_url={public_url_for(invitation.token)}")

    await notification_service.notify_user(
        db, recipient_id=user.id, type="INTERVIEW_SCHEDULED",
        title="Entretien proposé",
        message=f"Un entretien vous a été proposé pour « {job.title} ». Choisissez votre créneau.",
        link="/frontoffice/applications",
    )
    await notification_service.notify_admins(
        db, actor=current_user, type="INTERVIEW_SCHEDULED",
        title="Entretien planifié",
        message=(f"{current_user.full_name or current_user.username} a planifié un entretien "
                 f"pour {candidate.full_name} ({job.title})."),
        link="/admin/interviews",
    )
    await db.commit()

    return WorkflowResponse(
        message="Invitation d'entretien envoyée. Le candidat va recevoir un lien pour choisir son créneau.",
        application_id=app_id,
        email_sent=True,
    )


@router.post(
    "/applications/{app_id}/reject",
    response_model=WorkflowResponse,
    dependencies=[Depends(require("workflow", "write"))],
)
async def reject_application(
    app_id: UUID,
    body: RejectRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reject the application and send a rejection email to the candidate."""
    app, candidate, user, job = await _get_application_context(db, app_id)

    app.status = ApplicationStatus.REJECTED.value
    await db.commit()

    background_tasks.add_task(
        send_rejection_email,
        user.email,
        candidate.full_name,
        job.title,
        body.message,
    )

    await notification_service.notify_user(
        db, recipient_id=user.id, type="APPLICATION_STATUS_CHANGED",
        title="Candidature rejetée",
        message=f"Votre candidature pour « {job.title} » n'a pas été retenue.",
        link="/frontoffice/applications",
    )
    await notification_service.notify_admins(
        db, actor=current_user, type="APPLICATION_STATUS_CHANGED",
        title="Candidature rejetée",
        message=(f"{current_user.full_name or current_user.username} a rejeté la candidature "
                 f"de {candidate.full_name} ({job.title})."),
        link="/admin/applications",
    )
    await db.commit()

    logger.info(f"Application {app_id} rejected, email queued to {user.email}")
    return WorkflowResponse(
        message="Candidature rejetée. Email de refus envoyé.",
        application_id=app_id,
        email_sent=True,
    )


@router.post(
    "/applications/{app_id}/start-negotiation",
    dependencies=[Depends(require("workflow", "write"))],
)
async def start_negotiation(
    app_id: UUID,
    body: StartNegotiationRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Mark the application as NEGOTIATION and RUN the salary-negotiation agent
    end-to-end (salary prediction + offer evaluation + simulated counter-offers),
    returning the full outcome so the RH sees the result immediately.
    """
    app, candidate, user, job = await _get_application_context(db, app_id)

    app.status = ApplicationStatus.NEGOTIATION.value
    await db.commit()

    await notification_service.notify_user(
        db, recipient_id=user.id, type="NEGOTIATION_STARTED",
        title="Négociation salariale lancée",
        message=f"Une négociation salariale a démarré pour « {job.title} ».",
        link="/frontoffice/applications",
    )
    await notification_service.notify_admins(
        db, actor=current_user, type="NEGOTIATION_STARTED",
        title="Négociation salariale lancée",
        message=(f"{current_user.full_name or current_user.username} a lancé une négociation "
                 f"pour {candidate.full_name} ({job.title})."),
        link="/admin/negotiation",
    )
    await db.commit()

    # Features poste (compétences requises) + candidat (expérience réelle
    # extraite du CV, score de matching) : la prédiction dépend du COUPLE
    # poste × candidat, pas seulement du poste.
    profile = await _get_candidate_profile(db, app_id, job)
    skills_blob = " ".join(s.lower() for s in (job.required_skills or []))
    job_data = {
        "job_id": str(app_id),
        "title": job.title,
        "description": job.description or "",
        "rating": 3.5,
        "experience_years": profile["experience_years"],
        "skills_text": skills_blob,
        "candidate_match_score": profile["match_score"],
        "python": 1 if "python" in skills_blob else 0,
        "spark": 1 if "spark" in skills_blob else 0,
        "aws": 1 if "aws" in skills_blob else 0,
        "excel": 1 if "excel" in skills_blob else 0,
    }

    try:
        from app.services.salary_prediction_service import get_salary_service
        from app.agents.decision_agent import get_negotiation_agent

        prediction = await asyncio.to_thread(lambda: get_salary_service().predict_salary(job_data))
        agent = get_negotiation_agent()
        result = await agent.initiate_negotiation(
            job_id=str(app_id),
            candidate_id=str(candidate.id),
            job_data=job_data,
            employer_offer=body.employer_offer,
        )
        logger.info(f"Negotiation executed for application {app_id}: "
                    f"{result.get('negotiation_status')} @ {result.get('final_salary')}k")

        # Persister la négociation issue du workflow RH (best-effort).
        try:
            from app.services.negotiation_repository import negotiation_repository
            await negotiation_repository.persist_agent_run(
                db, candidate_id=str(candidate.id), result=result, job_offer_id=job.id
            )
            await db.commit()
        except Exception as persist_exc:  # pragma: no cover - defensive
            logger.warning(f"Persistance de la négociation (workflow) échouée: {persist_exc}")
        return {
            "message": "Négociation exécutée par l'agent IA.",
            "application_id": str(app_id),
            "candidate_name": candidate.full_name,
            "employer_offer": body.employer_offer,
            "predicted_salary": prediction.get("predicted_salary"),
            "confidence": prediction.get("confidence"),
            "predicted_range": [prediction.get("range_min"), prediction.get("range_max")],
            "model_type": prediction.get("model_type"),
            "candidate_experience_years": profile["experience_years"],
            "candidate_experience_source": profile["experience_source"],
            "candidate_match_score": profile["match_score"],
            "negotiation_status": result.get("negotiation_status"),
            "final_salary": result.get("final_salary"),
            "rounds": result.get("negotiation_rounds"),
            "reason": result.get("reason"),
            "summary": result.get("summary"),
        }
    except Exception as exc:  # pragma: no cover - keep the status change even if the agent fails
        logger.error(f"Negotiation agent failed for application {app_id}: {exc}", exc_info=True)
        return {
            "message": "Statut mis à jour en « Négociation » (moteur indisponible).",
            "application_id": str(app_id),
            "employer_offer": body.employer_offer,
            "error": str(exc),
        }


@router.post(
    "/applications/{app_id}/negotiation-analysis",
    response_model=NegotiationAnalysisResponse,
    dependencies=[Depends(require("workflow", "write"))],
)
async def negotiation_analysis(
    app_id: UUID,
    body: NegotiationAnalysisRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Analyse dédiée à la page « Négociation » : le RH choisit une offre, un
    candidat parmi ceux ayant postulé, saisit le salaire demandé et la
    fourchette budgétaire du poste (éditable).

    Trois grandeurs sont tenues séparées, et c'est le cœur de la correction :

      - le **budget de l'offre** (`budget_min` … `budget_max`) — seule
        référence pour dire si la demande « rentre » ; le seuil de dépassement
        est le MAXIMUM annoncé, pas le minimum ;
      - la **demande** du candidat ;
      - le **marché**, restitué en FOURCHETTE par le modèle ML, jamais comme
        un montant unique.

    Ce n'est PAS le simulateur poste-seul (`/negotiations/initiate`) : ici la
    prédiction et la décision dépendent du couple poste × candidat.
    """
    application, candidate, user, job = await _get_application_context(db, app_id)
    profile = await _get_candidate_profile(db, app_id, job)

    from app.services.negotiation_analysis_service import negotiation_analysis_service

    candidate_experience = profile["experience_years"]
    required_experience = job.required_experience_years

    # Deux bandes de marché distinctes (poste / candidat) : calcul partagé
    # avec l'aide à la décision, voir `candidate_market_bands`.
    bands = await candidate_market_bands(job, candidate_experience)

    # Budget = la FOURCHETTE de l'offre. Le seuil de dépassement est le MAXIMUM
    # annoncé, pas le minimum : un candidat qui demande le haut de fourchette ne
    # dépasse rien du tout.
    budget_min = float(
        body.base_salary if body.base_salary is not None
        else (job.salary_min or bands["market_min"])
    )
    budget_max = float(
        body.base_salary_max if body.base_salary_max is not None
        else (job.salary_max or max(budget_min, bands["market_reference"]))
    )

    analysis = negotiation_analysis_service.analyze(
        candidate_name=candidate.full_name,
        budget_min=budget_min,
        budget_max=budget_max,
        requested_salary=body.requested_salary,
        market_min=bands["market_min"],
        market_max=bands["market_max"],
        market_reference=bands["market_reference"],
        candidate_experience_years=candidate_experience,
        required_experience_years=required_experience,
        match_score=profile["match_score"],
        seniority_label=bands["job"]["seniority_label"],
        experience_source=profile["experience_source"],
    )

    return NegotiationAnalysisResponse(
        candidate_name=candidate.full_name,
        job_title=job.title,
        candidate_experience_years=candidate_experience,
        experience_source=profile["experience_source"],
        required_experience_years=required_experience,
        experience_gap_years=analysis["experience_gap_years"],
        match_score=profile["match_score"],
        qualification_score=analysis["qualification_score"],
        market_min=analysis["market_min"],
        market_max=analysis["market_max"],
        market_reference=analysis["market_reference"],
        market_gap=analysis["market_gap"],
        job_seniority_label=bands["job"]["seniority_label"],
        confidence=float(bands.get("confidence") or 0),
        budget_min=analysis["budget_min"],
        budget_max=analysis["budget_max"],
        budget_overrun=analysis["budget_overrun"],
        position_in_range=analysis["position_in_range"],
        requested_salary=body.requested_salary,
        verdict=analysis["verdict"],
        decision=analysis["decision"],
        negotiation_score=analysis["negotiation_score"],
        score_breakdown=analysis["score_breakdown"],
        signals=analysis["signals"],
        is_qualified=analysis["is_qualified"],
        is_exceptional=analysis["is_exceptional"],
        recommended_salary=analysis["recommended_salary"],
        explanation=analysis["explanation"],
        explanation_lines=analysis["explanation_lines"],
        # Rétro-compatibilité : le « salaire prédit » devient le point de
        # référence marché, la « fourchette prédite » la fourchette de marché.
        predicted_salary=analysis["market_reference"],
        predicted_range=[analysis["market_min"], analysis["market_max"]],
        base_salary=analysis["budget_min"],
    )


@router.post(
    "/applications/{app_id}/negotiation-chat",
    response_model=NegotiationChatResponse,
    dependencies=[Depends(require("workflow", "write"))],
)
async def negotiation_chat(
    app_id: UUID,
    body: NegotiationChatRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Assistant conversationnel de négociation pour CE candidat sur CETTE offre.

    Le RH peut écrire librement (« le candidat demande 4500 », « et si je
    propose 4200 ? », « compare-le aux autres candidats »...). Le contexte
    (poste, profil réel du candidat, budget, autres candidats sur l'offre)
    est injecté à chaque appel — l'assistant ne voit donc jamais un chiffre
    hors contexte. Utilise Claude quand une clé API est configurée, sinon
    bascule sur un raisonnement déterministe basé sur le même moteur de
    décision que `start-negotiation` (toujours une réponse, jamais un blocage).
    """
    application, candidate, user, job = await _get_application_context(db, app_id)
    profile = await _get_candidate_profile(db, app_id, job)
    others = await _get_other_candidates(db, job.id, app_id)

    from app.services.salary_prediction_service import get_salary_service
    from app.services.negotiation_analysis_service import negotiation_analysis_service

    skills_blob = " ".join(s.lower() for s in (job.required_skills or []))
    bands = await asyncio.to_thread(lambda: get_salary_service().negotiation_bands(
        title=job.title,
        skills_text=skills_blob,
        description=job.description or "",
        required_experience_years=job.required_experience_years,
        candidate_experience_years=profile["experience_years"],
    ))
    # Le point de référence marché ; l'assistant doit raisonner sur la
    # fourchette, ce montant n'est qu'un repère central.
    predicted_salary = bands["market_reference"]
    budget_min = float(job.salary_min or bands["market_min"])
    budget_max = float(job.salary_max or max(budget_min, bands["market_reference"]))

    experience_origin = {
        "candidate_score": "(chiffre du modèle de classement)",
        "cv": "(extraite de son CV)",
    }.get(profile["experience_source"], "(CV non analysé — valeur du poste utilisée par défaut)")

    context_lines = [
        f"Poste : {job.title}",
        "BUDGET DE L'OFFRE (seul montant qui engage l'entreprise) : "
        + (f"{budget_min:.0f} à {budget_max:.0f} TND/mois"
           if job.salary_min and job.salary_max else
           f"non renseigné dans l'offre — estimé à {budget_min:.0f}-{budget_max:.0f} TND"),
        "Expérience requise par l'offre : "
        + (f"{job.required_experience_years:.0f} ans" if job.required_experience_years is not None else "non précisée"),
        f"Compétences requises : {', '.join(job.required_skills or []) or 'non renseignées'}",
        f"Candidat : {candidate.full_name}",
        f"Expérience du candidat : {profile['experience_years']} ans {experience_origin}",
        f"Score de matching CV/poste : {profile['match_score']:.0f}/100" if profile["match_score"] is not None else "Score de matching : indisponible (CV pas encore scoré)",
        f"MARCHÉ ESTIMÉ (fourchette, pas un montant unique) : "
        f"{bands['market_min']:.0f} à {bands['market_max']:.0f} TND/mois, "
        f"repère central {predicted_salary:.0f} TND "
        f"— niveau du poste : {bands['job']['seniority_label']}, "
        f"niveau du candidat : {bands['candidate']['seniority_label']}",
    ]
    if others:
        context_lines.append("Autres candidats sur cette offre (pour comparaison budget) :")
        for o in others:
            context_lines.append(
                f"  - {o['candidate_name']} : score {o['match_score']:.0f}/100, statut {o['status']}"
            )
    else:
        context_lines.append("Aucun autre candidat scoré sur cette offre pour le moment.")
    context_block = "\n".join(context_lines)

    system_prompt = (
        "Tu es un assistant RH spécialisé en négociation salariale pour PIQBIT, "
        "une plateforme de recrutement tunisienne. Tu aides un recruteur humain "
        "à décider s'il doit accepter, contre-proposer ou refuser une demande "
        "salariale d'un candidat précis, pour un poste précis. Base-toi UNIQUEMENT "
        "sur le contexte fourni (poste, profil réel du candidat, budget, autres "
        "candidats). Réponds en français, de façon concise (3-5 phrases), donne "
        "toujours une recommandation claire (accepter / contre-proposer un montant "
        "précis / refuser) avec une justification courte. Si le RH mentionne "
        "d'autres candidats ou le budget global, aide-le à arbitrer entre eux.\n"
        "RÈGLES DE RAISONNEMENT, à respecter strictement :\n"
        "1. Une demande est « dans le budget » tant qu'elle ne dépasse pas le "
        "MAXIMUM de la fourchette de l'offre — jamais son minimum. Demander "
        "exactement le maximum annoncé ne constitue AUCUN dépassement.\n"
        "2. Le marché est une FOURCHETTE : ne compare jamais la demande à un "
        "montant unique et n'annonce jamais d'« écart au marché » quand la "
        "demande est comprise dans cette fourchette.\n"
        "3. Une expérience supérieure à celle requise justifie le HAUT de la "
        "fourchette de l'offre, pas un montant au-delà du budget.\n"
        "4. Si le budget de l'offre est sous le plancher du marché, signale-le "
        "au RH comme un risque de rétention, sans pour autant recommander de "
        "dépasser le budget de sa propre initiative."
    )

    history_block = "\n".join(f"{m.role}: {m.content}" for m in body.history[-10:])
    prompt = f"CONTEXTE:\n{context_block}\n\nHISTORIQUE:\n{history_block}\n\nRH: {body.message}"

    # Le contexte nomme le candidat ET ses concurrents, avec leurs scores et la
    # demande salariale : ce sont des données personnelles. Elles ne partent
    # que vers le modèle LOCAL (voir app/integrations/llm_router.py) ; s'il est
    # indisponible, le moteur de décision déterministe ci-dessous répond.
    reponse = await llm_router.generer(
        prompt, donnees_personnelles=True, system=system_prompt, max_tokens=400,
    )
    if reponse:
        return NegotiationChatResponse(
            reply=reponse.texte,
            recommendation=None,
            suggested_amount=None,
            predicted_salary=predicted_salary,
            source="llm",
        )

    # Fallback déterministe (modèle local indisponible) : même moteur de
    # décision que la négociation automatique, appliqué au montant que le RH
    # vient de mentionner dans son message, s'il y en a un.
    import re

    numbers = re.findall(r"\d[\d\s]{2,}", body.message.replace(",", "."))
    asked_amount = float(numbers[0].replace(" ", "")) if numbers else None

    if asked_amount is not None:
        # Même moteur de décision que la page d'analyse : le RH ne peut pas
        # obtenir deux verdicts contradictoires selon l'écran qu'il utilise.
        analysis = negotiation_analysis_service.analyze(
            candidate_name=candidate.full_name,
            budget_min=budget_min,
            budget_max=budget_max,
            requested_salary=asked_amount,
            market_min=bands["market_min"],
            market_max=bands["market_max"],
            market_reference=bands["market_reference"],
            candidate_experience_years=profile["experience_years"],
            required_experience_years=job.required_experience_years,
            match_score=profile["match_score"],
            seniority_label=bands["job"]["seniority_label"],
            experience_source=profile["experience_source"],
        )
        recommendation = {
            "acceptable": "accept",
            "counter_offer": "counter",
            "stretch": "counter",
            "negotiation_required": "counter",
        }.get(analysis["verdict"])
        reply = analysis["explanation"]
        if others:
            best_other = others[0]
            reply += (
                f" Pour comparaison, {best_other['candidate_name']} a un score de "
                f"{best_other['match_score']:.0f}/100 sur ce même poste."
            )
        return NegotiationChatResponse(
            reply=reply,
            recommendation=recommendation,
            suggested_amount=analysis["recommended_salary"],
            predicted_salary=predicted_salary,
            source="heuristic",
        )

    # No amount detected → give the RH the situational summary instead.
    reply = (
        f"Pour {candidate.full_name} sur « {job.title} », le budget de l'offre va de "
        f"{budget_min:.0f} à {budget_max:.0f} TND/mois et le marché estimé pour ce profil se situe "
        f"entre {bands['market_min']:.0f} et {bands['market_max']:.0f} TND. "
        f"Précisez le montant demandé par le candidat (ex. « il demande 4500 ») pour que je vous conseille."
    )
    if others:
        reply += f" {len(others)} autre(s) candidat(s) sont aussi scorés sur cette offre."
    return NegotiationChatResponse(
        reply=reply,
        recommendation=None,
        suggested_amount=None,
        predicted_salary=predicted_salary,
        source="heuristic",
    )
