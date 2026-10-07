"""
Contexte d'une candidature pour les écrans qui raisonnent sur le couple
poste × candidat (négociation salariale).

Sorti de `api/v1/endpoints/workflow.py` pour qu'un même calcul — expérience
retenue, bandes de marché — ne soit écrit qu'une fois et réutilisable par
tout nouvel écran, sans recopie.
"""
from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CVAnalysis, CandidateScore
from app.models.user import User


async def get_application_context(db: AsyncSession, application_id: UUID):
    """Return (application, candidate, user, job_offer) or raise 404."""
    result = await db.execute(
        select(Application, Candidate, User, JobOffer)
        .join(Candidate, Application.candidate_id == Candidate.id)
        .join(User, Candidate.user_id == User.id)
        .join(JobOffer, Application.job_offer_id == JobOffer.id)
        .where(Application.id == application_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return row  # (application, candidate, user, job_offer)


async def get_candidate_profile(db: AsyncSession, app_id: UUID, job: JobOffer) -> dict:
    """
    Profil du candidat pour CETTE candidature : expérience réelle + score de
    matching. C'est ce qui rend la négociation spécifique au candidat plutôt
    qu'au seul poste.

    L'expérience est lue EN PRIORITÉ dans l'instantané du modèle de classement
    (`CandidateScore.score_details["extracted_years"]`) : c'est le chiffre que
    le RH voit sur la page de classement, et c'est celui qui a réellement servi
    à calculer le score. La négociation et le classement ne peuvent donc plus
    afficher deux nombres différents. Replis successifs : l'analyse de CV
    courante, puis l'expérience requise par le poste (signalée comme telle).
    """
    cv_row = await db.execute(select(CVAnalysis).where(CVAnalysis.application_id == app_id))
    cv_analysis = cv_row.scalar_one_or_none()

    score_row = await db.execute(select(CandidateScore).where(CandidateScore.application_id == app_id))
    candidate_score = score_row.scalar_one_or_none()

    scored_years = None
    if candidate_score and isinstance(candidate_score.score_details, dict):
        scored_years = candidate_score.score_details.get("extracted_years")

    if scored_years is not None:
        experience_years, experience_source = float(scored_years), "candidate_score"
    elif cv_analysis and cv_analysis.extracted_experience_years is not None:
        experience_years, experience_source = cv_analysis.extracted_experience_years, "cv"
    else:
        experience_years, experience_source = job.required_experience_years, "job_requirement"

    return {
        "experience_years": experience_years,
        "experience_source": experience_source,
        "match_score": candidate_score.total_score if candidate_score else None,
        "extracted_skills": (cv_analysis.extracted_skills or []) if cv_analysis else [],
    }


async def candidate_market_bands(job: JobOffer, candidate_experience_years: Optional[float]) -> dict:
    """
    Bandes de marché poste × candidat, avec la confiance du modèle.

    Deux bandes distinctes : celle du POSTE (au niveau réellement demandé par
    l'offre) et celle du CANDIDAT (au niveau de son expérience) — voir
    `negotiation_bands`. Tout écran qui annonce un salaire prédit pour un
    candidat doit passer par ici, pour annoncer le même que la Négociation.

    scikit-learn est synchrone : le calcul sort de la boucle d'événements.
    """
    from app.services.salary_prediction_service import get_salary_service

    skills_blob = " ".join(s.lower() for s in (job.required_skills or []))

    def _bands() -> dict:
        service = get_salary_service()
        bands = service.negotiation_bands(
            title=job.title,
            skills_text=skills_blob,
            description=job.description or "",
            required_experience_years=job.required_experience_years,
            candidate_experience_years=candidate_experience_years,
        )
        bands["confidence"] = service.predict_salary({
            "title": job.title,
            "description": job.description or "",
            "experience_years": candidate_experience_years,
            "skills_text": skills_blob,
        }).get("confidence", 0.5)
        return bands

    return await asyncio.to_thread(_bands)
