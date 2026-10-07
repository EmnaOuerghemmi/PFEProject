from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CVAnalysisResponse(BaseModel):
    id: UUID
    application_id: UUID
    candidate_id: UUID
    extracted_skills: list[str]
    extracted_experience_years: float | None
    extracted_education_level: str
    extracted_job_titles: list[str]
    extracted_keywords: list[str]
    is_parsed: bool
    parsed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoreDetailsResponse(BaseModel):
    matched_skills: list[str]
    missing_skills: list[str] = []
    required_skills: list[str] | None
    extracted_years: float | None
    required_years: float | None
    extracted_education: str | None
    required_education: str | None
    weights: dict
    strengths: list[str] = []
    weaknesses: list[str] = []
    recommendation: str = ""


class CandidateScoreResponse(BaseModel):
    id: UUID
    application_id: UUID
    job_offer_id: UUID
    candidate_id: UUID
    total_score: float = Field(..., ge=0, le=100)
    skills_score: float = Field(..., ge=0, le=100)
    experience_score: float = Field(..., ge=0, le=100)
    education_score: float = Field(..., ge=0, le=100)
    rank: int | None
    score_details: dict | None
    computed_at: datetime

    model_config = {"from_attributes": True}


class CandidateRankingItem(BaseModel):
    candidate_id: UUID
    candidate_name: str | None = None
    application_id: UUID
    total_score: float = Field(..., ge=0, le=100)
    rank: int | None
    skills_score: float
    experience_score: float
    education_score: float
    score_details: dict | None
    # Active interview-invitation status for this candidate. Lets the UI
    # disable / relabel the "Planifier Entretien" button without an extra
    # round-trip per row.
    interview_status: str | None = None  # PENDING | CONFIRMED | None
    interview_invitation_id: UUID | None = None
    # Prétention annoncée par le candidat au dépôt de sa candidature (TND/mois).
    # Remontée ici pour que la page Négociation la pré-remplisse au lieu de la
    # faire ressaisir de mémoire par le RH.
    expected_salary: float | None = None
    interview_confirmed_at: datetime | None = None
    # Vrai quand l'entretien confirmé a déjà eu lieu : il reste au dossier mais
    # ne retient plus le bouton « Planifier » — un second entretien est possible.
    interview_ended: bool = False

    # ─── Test technique ───────────────────────────────────────────────────
    # État de la DERNIÈRE session de test de cette candidature, et sa note si
    # elle est corrigée. Mêmes raisons que pour l'entretien ci-dessus : sans
    # cela, l'écran de classement ferait une requête par candidat.
    test_status: str | None = None   # ENVOYE | EN_COURS | TERMINE | EXPIRE | ABANDONNE
    test_score: float | None = None

    # Éligibilité CALCULÉE PAR LE SERVEUR. Le navigateur n'a pas à connaître le
    # seuil : c'est une règle métier, et un chiffre dupliqué côté client finit
    # toujours par diverger. L'écran se contente d'afficher ou non le bouton.
    can_send_test: bool = False
    can_schedule_interview: bool = True


class JobRankingResponse(BaseModel):
    job_offer_id: UUID
    total_candidates: int
    ranking: list[CandidateRankingItem]


class AnalysisStartedResponse(BaseModel):
    message: str
    application_id: UUID | None = None
    job_id: UUID | None = None


class BulkAnalysisResponse(BaseModel):
    message: str
    job_id: UUID
    count_queued: int
