from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, status, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.db.session import get_db
from app.models.scoring import CandidateScore
from app.models.recruitment import Application
from app.services.decision_service import get_decision_service

router = APIRouter(
    dependencies=[Depends(require("decision", "read"))]
)


# ── Salary-offer evaluation (stateless) ─────────────────────────────────────

class EvaluateOfferRequest(BaseModel):
    predicted_salary: float = Field(..., gt=0)
    offered_salary: float = Field(..., gt=0)
    confidence: float = Field(default=0.7, ge=0, le=1)


class EvaluateOfferResponse(BaseModel):
    decision: str
    reason: str
    counter_offer: float | None = None


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


# ── Hiring recommendation (score-driven) ────────────────────────────────────

class HiringRecommendation(BaseModel):
    application_id: UUID
    total_score: float
    recommendation: str   # HIRE | INTERVIEW | HOLD | REJECT
    confidence: str       # high | medium | low
    rationale: str


@router.get("/applications/{app_id}/recommendation", response_model=HiringRecommendation)
async def hiring_recommendation(app_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Rule-based hiring recommendation derived from the candidate's computed
    score. Helps RH triage candidates consistently.
    """
    app = (await db.execute(select(Application).where(Application.id == app_id))).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    score = (await db.execute(
        select(CandidateScore).where(CandidateScore.application_id == app_id)
    )).scalar_one_or_none()
    if not score:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No score yet. Run CV analysis first.",
        )

    total = score.total_score
    if total >= 80:
        rec, conf = "HIRE", "high"
        rationale = "Score excellent — profil fortement aligné avec le poste."
    elif total >= 65:
        rec, conf = "INTERVIEW", "high"
        rationale = "Bon score — recommandé pour un entretien."
    elif total >= 50:
        rec, conf = "HOLD", "medium"
        rationale = "Score moyen — à conserver en liste d'attente."
    else:
        rec, conf = "REJECT", "medium"
        rationale = "Score faible — profil peu aligné avec les exigences."

    return HiringRecommendation(
        application_id=app_id,
        total_score=total,
        recommendation=rec,
        confidence=conf,
        rationale=rationale,
    )
