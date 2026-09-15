"""
Détail de candidature, vu par le candidat.

Deux champs sont volontairement **optionnels sans valeur par défaut visible** :
`test_score` et `interview_feedback`. Quand le RH n'a pas ouvert le partage,
ils sont ABSENTS de la réponse — pas à `null`.

La nuance n'est pas cosmétique. Un `null` accompagné d'un libellé apprendrait
au candidat qu'il existe une note qu'on lui refuse, et transformerait chaque
candidature en demande de partage. `model_dump(exclude_none=True)` côté
endpoint garantit l'absence.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """Un constat qui explique le score — jamais un jugement."""
    sujet: str
    constat: str


class Weights(BaseModel):
    """
    Pondération choisie pour CETTE offre.

    L'afficher est la forme la plus simple de transparence : le candidat sait
    ce qui compte le plus avant de se demander pourquoi il obtient ce score.
    """
    skills: float | None = None
    experience: float | None = None
    education: float | None = None


class ApplicationScoreDetail(BaseModel):
    # ── La candidature et son poste ───────────────────────────────────────
    application_id: UUID
    job_offer_id: UUID
    job_title: str
    job_description: str
    job_required_skills: list[str] = Field(default_factory=list)
    job_required_experience_years: float | None = None
    job_required_education_level: str | None = None
    job_salary_min: float | None = None
    job_salary_max: float | None = None
    job_work_mode: str | None = None
    job_contract_types: list[str] = Field(default_factory=list)
    applied_at: datetime
    status: str

    #: Faux tant que l'analyse du CV n'a pas tourné. L'écran doit alors le dire
    #: plutôt qu'afficher zéro, qui se lirait comme une note catastrophique.
    analysis_ready: bool = False

    # ── La correspondance ─────────────────────────────────────────────────
    score: float | None = None
    band: str | None = None
    summary: str | None = None
    weights: Weights | None = None

    skills_matched: list[str] = Field(default_factory=list)
    skills_missing: list[str] = Field(default_factory=list)
    skills_required: list[str] = Field(default_factory=list)

    experience_detected_years: float | None = None
    experience_required_years: float | None = None
    education_detected: str | None = None
    education_required: str | None = None

    observations: list[Observation] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)

    # ── Ce que le RH a choisi de partager ─────────────────────────────────
    # Absents de la réponse quand le partage est fermé. Voir le docstring.
    test_score: float | None = None
    interview_feedback: str | None = None


class CandidateVisibilityUpdate(BaseModel):
    """Ce que le RH ouvre ou referme, candidature par candidature."""
    test_score_visible: bool | None = None
    interview_feedback_visible: bool | None = None
    #: Retour rédigé POUR le candidat — distinct des notes d'entretien, qui
    #: restent internes. Vider le champ revient à ne rien partager.
    candidate_feedback: str | None = Field(default=None, max_length=4000)


class CandidateVisibilityState(BaseModel):
    """L'état du partage, tel que le back-office l'affiche."""
    application_id: UUID
    test_score_visible: bool
    interview_feedback_visible: bool
    candidate_feedback: str | None = None
    #: Vrai quand une note de test existe — sans elle, ouvrir le partage ne
    #: montrerait rien, et l'écran doit pouvoir le signaler au RH.
    has_test_score: bool = False
