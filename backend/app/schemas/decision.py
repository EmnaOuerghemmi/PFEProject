"""Schémas de l'aide à la décision d'embauche."""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

Recommendation = Literal["HIRE", "INTERVIEW", "HOLD", "REJECT"]
Confidence = Literal["high", "medium", "low"]


class EvaluateOfferRequest(BaseModel):
    predicted_salary: float = Field(..., gt=0)
    offered_salary: float = Field(..., gt=0)
    confidence: float = Field(default=0.7, ge=0, le=1)


class EvaluateOfferResponse(BaseModel):
    decision: str
    reason: str
    counter_offer: Optional[float] = None


class TestSignals(BaseModel):
    """Ce que le test dit au-delà de sa note — sert au départage."""
    status: Optional[str] = None
    score: Optional[float] = None
    hard_success_rate: Optional[float] = Field(None, description="0–1, questions difficiles")
    hard_total: int = 0
    anomaly_count: int = 0
    overrun_questions: int = 0


class InterviewSignals(BaseModel):
    score: Optional[float] = None
    status: Optional[str] = Field(None, description="Invitation en cours : PENDING / CONFIRMED")
    has_notes: bool = False


class CvSignals(BaseModel):
    score: float
    skills_score: float
    experience_score: float
    education_score: float
    matched_skills: int
    missing_skills: int


class CompositeView(BaseModel):
    score: Optional[float]
    completeness: int
    available: list[str]
    missing: list[str]
    band: str


class TieBreak(BaseModel):
    group_size: int
    score: int
    decided_by: Optional[str] = None
    explanation: str


class HiringRecommendation(BaseModel):
    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    decision_rank: int
    recommendation: Recommendation
    confidence: Confidence
    #: Verdict chiffré, en une phrase.
    rationale: str
    #: Points forts, chacun vérifiable dans le dossier.
    strengths: list[str] = []
    #: Points de vigilance — jamais soustraits de la note.
    warnings: list[str] = []
    #: L'action la plus utile maintenant.
    next_step: str = ""
    composite: CompositeView
    cv: CvSignals
    test: TestSignals
    interview: InterviewSignals
    expected_salary: Optional[float] = None
    tie: Optional[TieBreak] = None
    # Conservé pour les appelants existants : la note du CV seul.
    total_score: float
    #: Statut actuel de la candidature (vocabulaire `application_status`).
    application_status: Optional[str] = None


class ApplyDecisionRequest(BaseModel):
    """Appliquer une recommandation : elle devient le statut de la candidature."""
    decision: Literal["HIRE", "REJECT", "HOLD"]
    #: Mot ajouté à l'e-mail de refus (facultatif, ignoré pour les autres décisions).
    message: str = Field(default="", max_length=2000)


class ApplyDecisionResponse(BaseModel):
    application_id: UUID
    application_status: str
    email_sent: bool


class JobRecommendations(BaseModel):
    job_offer_id: UUID
    bands: dict[str, float]
    candidates: list[HiringRecommendation]
