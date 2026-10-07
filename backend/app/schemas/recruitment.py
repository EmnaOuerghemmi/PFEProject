from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import application_status

# Valeurs autorisées pour les conditions du poste. Centralisées ici pour que
# le schéma de création, celui de mise à jour et le filtre de listing ne
# puissent pas diverger.
WORK_MODE_PATTERN = "^(ON_SITE|HYBRID|REMOTE)$"
CONTRACT_TYPE_PATTERN = "^(CDI|CDD|SIVP|STAGE|FREELANCE)$"
CONTRACT_TYPES = ("CDI", "CDD", "SIVP", "STAGE", "FREELANCE")


def _valider_types_contrat(v: list[str] | None) -> list[str] | None:
    """
    Valide et dédoublonne la liste des types de contrat d'une offre.

    Une liste vide est ramenée à None : « aucun type précisé » et « liste
    vide » désignent la même chose côté métier, autant n'en stocker qu'une
    seule forme. L'ordre de saisie est conservé — c'est celui de l'affichage.
    """
    if v is None:
        return None
    vus: list[str] = []
    for t in v:
        if t not in CONTRACT_TYPES:
            raise ValueError(f"Type de contrat inconnu : {t}. Attendu parmi {list(CONTRACT_TYPES)}.")
        if t not in vus:
            vus.append(t)
    return vus or None
JOB_STATUS_PATTERN = "^(DRAFT|PUBLISHED|CLOSED)$"


def _valider_fourchette(model):
    """
    Une fourchette salariale doit être ordonnée.

    Sans ce contrôle, un `salary_min` supérieur au `salary_max` traverse toute
    l'application : le moteur de négociation compare alors la demande à un
    plafond inférieur au plancher, et l'analyse devient absurde.
    """
    minimum, maximum = model.salary_min, model.salary_max
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(
            f"Le salaire minimum ({minimum:.0f}) ne peut pas dépasser le maximum ({maximum:.0f})."
        )
    return model


class JobExtractionRequest(BaseModel):
    """Le texte libre que le RH décrit — trois mots à trois paragraphes."""
    text: str = Field(..., min_length=10, max_length=4000)


class JobExtractionFields(BaseModel):
    """
    Ce que l'agent a extrait — un sous-ensemble de `JobOfferCreate`.

    Tous les champs sont facultatifs et absents plutôt qu'à `null` quand le
    texte source ne les mentionne pas : le formulaire ne doit recevoir QUE ce
    que le RH a réellement dit, jamais une valeur devinée qui se ferait
    passer pour un fait.
    """
    title: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    required_experience_years: float | None = None
    required_education_level: str | None = None
    work_mode: str | None = None
    contract_types: list[str] | None = None


class JobExtractionResponse(BaseModel):
    ok: bool
    fields: JobExtractionFields
    #: Motif d'un échec — absent d'un pouce, à afficher tel quel au RH.
    reason: str | None = None


class JobOfferCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10)
    salary_min: float | None = Field(default=None, gt=0, le=200_000)
    salary_max: float | None = Field(default=None, gt=0, le=200_000)
    required_skills: list[str] | None = None
    # Une expérience requise négative n'a aucun sens et fausse silencieusement
    # le scoring comme la négociation : bornée dès la saisie.
    required_experience_years: float | None = Field(default=None, ge=0, le=50)
    required_education_level: str | None = None
    weight_skills: float = 0.5
    weight_experience: float = 0.3
    weight_education: float = 0.2
    work_mode: str | None = Field(default=None, pattern=WORK_MODE_PATTERN)
    contract_types: list[str] | None = None
    status: str = Field(default="PUBLISHED", pattern=JOB_STATUS_PATTERN)
    expires_at: datetime | None = None

    @field_validator("contract_types")
    @classmethod
    def types_contrat_valides(cls, v: list[str] | None) -> list[str] | None:
        return _valider_types_contrat(v)

    @model_validator(mode="after")
    def fourchette_ordonnee(self):
        return _valider_fourchette(self)


class JobOfferUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    salary_min: float | None = Field(default=None, gt=0, le=200_000)
    salary_max: float | None = Field(default=None, gt=0, le=200_000)
    required_skills: list[str] | None = None
    required_experience_years: float | None = Field(default=None, ge=0, le=50)
    required_education_level: str | None = None
    weight_skills: float | None = None
    weight_experience: float | None = None
    weight_education: float | None = None
    is_active: bool | None = None
    work_mode: str | None = Field(default=None, pattern=WORK_MODE_PATTERN)
    contract_types: list[str] | None = None
    status: str | None = Field(default=None, pattern=JOB_STATUS_PATTERN)
    expires_at: datetime | None = None

    @field_validator("contract_types")
    @classmethod
    def types_contrat_valides(cls, v: list[str] | None) -> list[str] | None:
        return _valider_types_contrat(v)

    @model_validator(mode="after")
    def fourchette_ordonnee(self):
        return _valider_fourchette(self)


class JobOfferResponse(BaseModel):
    id: UUID
    title: str
    description: str
    salary_min: float | None
    salary_max: float | None
    required_skills: list[str] | None
    required_experience_years: float | None
    required_education_level: str | None
    weight_skills: float
    weight_experience: float
    weight_education: float
    is_active: bool
    work_mode: str | None = None
    contract_types: list[str] | None = None
    status: str = "PUBLISHED"
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CandidateCreate(BaseModel):
    full_name: str = Field(..., min_length=3)
    phone: str | None = None


class CandidateResponse(BaseModel):
    id: UUID
    user_id: UUID
    full_name: str
    phone: str | None
    cv_path: str | None
    cv_filename: str | None = None
    cv_uploaded_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateCvResponse(BaseModel):
    """
    État du CV de référence, tel que l'affiche l'espace candidat.

    Le CHEMIN du fichier n'est volontairement pas exposé : il ne sert à rien au
    client et publier l'arborescence du serveur invite à tenter d'y accéder
    directement. Seuls le nom d'origine et la date de dépôt remontent.
    """
    has_cv: bool
    filename: str | None = None
    uploaded_at: datetime | None = None

    @classmethod
    def from_candidate(cls, candidate) -> "CandidateCvResponse":
        return cls(
            has_cv=bool(candidate.cv_path),
            filename=candidate.cv_filename,
            uploaded_at=candidate.cv_uploaded_at,
        )


class CvVerificationResponse(BaseModel):
    """
    Verdict de la vérification préalable d'un document, quand il n'est PAS
    bloquant — un refus arrive en 400, avec le message destiné au candidat.

    La probabilité n'est pas renvoyée : sur une route publique, elle
    permettrait d'ajuster un document jusqu'à franchir le seuil.
    """
    decision: Literal["accepte", "incertain", "non_verifie"]


class ExpectedSalaryUpdate(BaseModel):
    """
    Prétention salariale du candidat, en TND mensuels bruts.

    `None` est accepté : il exprime « je préfère ne pas répondre » et permet
    aussi d'effacer un montant saisi par erreur. La borne haute écarte les
    fautes de frappe évidentes (un salaire annuel saisi comme mensuel).
    """
    expected_salary: float | None = Field(default=None, gt=0, le=200_000)


class ApplicationCreate(BaseModel):
    job_offer_id: UUID


class ApplicationUpdate(BaseModel):
    """
    Changement de statut à la main par un RH.

    La regex qui vivait ici n'admettait que quatre valeurs, alors que le code
    en écrivait quatre autres directement sur le modèle — en la contournant.
    La validation porte désormais sur le vocabulaire partagé.
    """
    status: str

    @field_validator("status")
    @classmethod
    def _statut_connu(cls, v: str) -> str:
        if not application_status.is_valid(v):
            raise ValueError(
                f"Statut inconnu : « {v} ». Valeurs admises : "
                + ", ".join(application_status.ALL)
            )
        return v


class ApplicationResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    candidate_name: str | None = None
    job_offer_id: UUID
    job_offer_title: str | None = None
    cv_file_path: str
    status: str
    expected_salary: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedJobOffers(BaseModel):
    total: int
    page: int
    size: int
    items: list[JobOfferResponse]


class JobRecommendation(BaseModel):
    """
    Une offre recommandée à un candidat d'après son CV analysé.

    Projection volontairement réduite : une recommandation est une invitation
    à cliquer, pas une fiche d'offre.

    `compatibility_score` (0..1) combine les critères métier — compétences,
    expérience, formation, pondérés par l'offre elle-même — et la proximité
    sémantique CV ↔ offre. Il mesure une ADÉQUATION DE PROFIL, jamais une
    probabilité d'être retenu : `reasons` existe pour que le candidat puisse
    lire d'où vient le chiffre au lieu de le subir.
    """
    job_id: UUID
    title: str
    compatibility_score: float
    matching_skills: list[str] = []
    missing_skills: list[str] = []
    reasons: list[str] = []
    salary_min: float | None = None
    salary_max: float | None = None
    work_mode: str | None = None
    contract_types: list[str] = []


class JobRecommendations(BaseModel):
    """Enveloppe de la réponse — `recommendations: []` quand rien ne colle."""
    recommendations: list[JobRecommendation] = []


class MyApplicationResponse(BaseModel):
    """Application enriched with job offer details — for the candidate's own list."""
    id: UUID
    job_offer_id: UUID
    candidate_id: UUID
    cv_file_path: str
    status: str
    expected_salary: float | None = None
    created_at: datetime
    updated_at: datetime

    # joined job offer fields
    job_title: str
    job_description: str
    job_salary_min: float | None = None
    job_salary_max: float | None = None
    job_required_skills: list[str] | None = None
    job_required_experience_years: float | None = None
    job_required_education_level: str | None = None
    job_is_active: bool
    job_work_mode: str | None = None
    job_contract_types: list[str] | None = None

    # optional score data (if scoring has been computed)
    total_score: float | None = None
    skills_score: float | None = None
    experience_score: float | None = None
    education_score: float | None = None

    model_config = {"from_attributes": True}
