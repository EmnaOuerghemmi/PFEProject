"""
Schémas du test technique.

La séparation la plus importante de ce module est celle entre ce que voit le
**candidat** et ce que voit le **RH**. Une question servie au candidat ne porte
ni sa bonne réponse, ni son explication, ni son budget de temps — sinon le test
se lit dans l'onglet réseau du navigateur. Deux schémas distincts valent mieux
qu'un schéma commun dont on espère filtrer les champs au bon endroit.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.assessment import (
    DEFAULT_DURATION_MINUTES, AnswerOutcome, QuestionDifficulty, QuestionKind,
    QuestionStatus, SessionStatus,
)

# Une réponse est toujours une liste, quel que soit le type de question : la
# correction n'a ainsi qu'un seul cas à traiter.
AnswerValue = list[str] | None


# ── Vivier (back-office) ──────────────────────────────────────────────────────

class QuestionCreate(BaseModel):
    statement: str = Field(..., min_length=10, max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=8)
    correct_answer: list[str] = Field(..., min_length=1, max_length=8)
    explanation: str | None = Field(default=None, max_length=2000)
    difficulty: QuestionDifficulty = QuestionDifficulty.MOYENNE
    kind: QuestionKind = QuestionKind.QCM_UNIQUE
    skill_tag: str | None = Field(default=None, max_length=80)
    expected_seconds: int | None = Field(default=None, ge=10, le=900)

    @field_validator("correct_answer", mode="before")
    @classmethod
    def toujours_une_liste(cls, v):
        if v is None:
            return v
        return v if isinstance(v, list) else [v]


class QuestionUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=10, max_length=2000)
    options: list[str] | None = Field(default=None, max_length=8)
    correct_answer: list[str] | None = Field(default=None, min_length=1, max_length=8)
    explanation: str | None = Field(default=None, max_length=2000)
    difficulty: QuestionDifficulty | None = None
    kind: QuestionKind | None = None
    skill_tag: str | None = Field(default=None, max_length=80)
    expected_seconds: int | None = Field(default=None, ge=10, le=900)


class QuestionResponse(BaseModel):
    """Vue RH — complète, bonne réponse comprise."""
    id: UUID
    job_offer_id: UUID
    statement: str
    options: list[str] | None
    correct_answer: list[str]
    explanation: str | None
    difficulty: QuestionDifficulty
    kind: QuestionKind
    status: QuestionStatus
    expected_seconds: int
    skill_tag: str | None
    generated_by: str | None
    times_served: int
    times_correct: int
    times_skipped: int
    success_rate: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BankCoverage(BaseModel):
    """
    Ce que l'écran de sélection affiche en permanence.

    Sans ces compteurs sous les yeux, un RH décoche librement et envoie un test
    déséquilibré sans s'en apercevoir.
    """
    total: int
    par_difficulte: dict[str, int]
    gabarit: dict[str, int]
    competences_couvertes: list[str]
    competences_manquantes: list[str]


class TestPreparation(BaseModel):
    """Les questions présélectionnées, avec l'état de la couverture."""
    questions: list[QuestionResponse]
    coverage: BankCoverage


class SendTestRequest(BaseModel):
    question_ids: list[UUID] = Field(..., min_length=1, max_length=40)
    duration_minutes: int = Field(default=DEFAULT_DURATION_MINUTES, ge=5, le=180)


# ── Passage (candidat) ────────────────────────────────────────────────────────

class PublicTestIntro(BaseModel):
    """
    Écran d'accueil. Ce qui est annoncé au candidat, et rien de plus.

    La limite globale est dite ; le budget par question ne l'est pas — il ne
    bloque rien et n'entre pas dans la note.
    """
    job_title: str
    question_count: int
    duration_minutes: int
    status: SessionStatus
    already_submitted: bool
    link_expired: bool


class PublicQuestion(BaseModel):
    """
    Vue candidat — volontairement amputée.

    Ni `correct_answer`, ni `explanation`, ni `expected_seconds`, ni
    `difficulty` : chacun de ces champs, servi au navigateur, renseigne sur la
    réponse ou sur ce qu'on attend du candidat.
    """
    position: int
    total: int
    statement: str
    options: list[str]
    kind: QuestionKind
    seconds_remaining: int          # temps GLOBAL restant, calculé par le serveur


class SubmitAnswerRequest(BaseModel):
    """
    `answer = None` vaut « Passer » — compté comme une erreur.

    Aucun champ de temps : le client ne renseigne jamais de durée, le serveur
    l'établit entre l'envoi de la question et la réception de la réponse.
    """
    position: int = Field(..., ge=1)
    answer: AnswerValue = None


class SubmitAnswerResponse(BaseModel):
    """
    Aucun retour sur la justesse : le candidat ne doit rien apprendre du
    barème pendant le test, sinon le vivier fuite question après question.
    """
    accepted: bool
    next_question: PublicQuestion | None
    finished: bool


class PublicTestResult(BaseModel):
    """Écran de fin. Ni note, ni correction."""
    finished: bool
    message: str


# ── Relecture (back-office) ───────────────────────────────────────────────────

class AnswerReview(BaseModel):
    """Une ligne de l'écran « Détail des réponses »."""
    position: int
    statement: str
    options: list[str] | None
    given_answer: list[str] | None
    correct_answer: list[str]
    outcome: AnswerOutcome
    difficulty: QuestionDifficulty
    skill_tag: str | None
    elapsed_seconds: int | None
    expected_seconds: int
    overrun_seconds: int


class SkillBreakdown(BaseModel):
    """
    Réussite par compétence.

    C'est la vue qui sert vraiment à l'entretien : savoir qu'un candidat a 65
    renseigne peu, savoir qu'il tient Angular et bute sur SQL donne au RH ses
    questions.
    """
    skill: str
    asked: int
    correct: int
    rate: float


class TestSessionSummary(BaseModel):
    """Vue RH d'une session — jamais exposée au candidat."""
    id: UUID
    application_id: UUID
    status: SessionStatus
    question_count: int
    duration_minutes: int
    sent_at: datetime
    started_at: datetime | None
    submitted_at: datetime | None
    score: float | None
    correct_count: int | None
    total_overrun_seconds: int
    overrun_question_count: int
    anomaly_flags: list[dict] | None

    model_config = {"from_attributes": True}


class TestSessionDetail(TestSessionSummary):
    outcome_counts: dict[str, int]
    by_skill: list[SkillBreakdown]
    answers: list[AnswerReview]


# ── Évaluation d'entretien et score composite ─────────────────────────────────

class InterviewNotesRequest(BaseModel):
    notes: str = Field(..., min_length=1, max_length=8000)


class InterviewScoreRequest(BaseModel):
    """`None` efface la note — le RH peut revenir sur sa décision."""
    interview_score: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=8000)


class CriterionSuggestion(BaseModel):
    score: float | None
    justification: str


class InterviewSuggestion(BaseModel):
    """
    Proposition du modèle — jamais une décision.

    `available=False` signale qu'aucun modèle n'a répondu : le RH saisit alors
    sa note directement. Un entretien ne doit pas rester en attente parce
    qu'une API est indisponible.
    """
    available: bool
    reason: str | None = None
    model: str | None = None
    suggested_at: str | None = None
    criteria: dict[str, CriterionSuggestion] = Field(default_factory=dict)
    overall: float | None = None
    summary: str = ""


class CompositeBreakdownItem(BaseModel):
    value: float
    weight: float          # poids RÉEL après renormalisation


class CompositeScore(BaseModel):
    """
    La note finale, jamais seule.

    `completeness` l'accompagne toujours : deux candidats notés sur un nombre
    de volets différent ne sont pas comparables, et une note de 69 sur un seul
    volet ne vaut pas une note de 69 sur trois.
    """
    score: float | None
    completeness: int
    available: list[str]
    missing: list[str]
    band: str
    uncertainty: int
    breakdown: dict[str, CompositeBreakdownItem]


class CandidateEvaluation(BaseModel):
    """Vue d'ensemble d'une candidature : les trois volets et leur composition."""
    application_id: UUID
    cv_score: float | None
    test_score: float | None
    interview_score: float | None
    interview_notes: str | None
    interview_ai_suggestion: dict | None
    composite: CompositeScore
