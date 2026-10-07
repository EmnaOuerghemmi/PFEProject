from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

#: Civilité écrite au contrat — accorde « né / née » et « demeurant ».
Civility = Literal["M.", "Mme"]


class ContractCreate(BaseModel):
    """Termes fournis à la création (le reste est prérempli côté serveur)."""
    contract_type: str = Field(default="CDI")
    position: str | None = Field(default=None, max_length=200)
    department: str | None = None
    salary: float | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    trial_period_months: int = Field(default=3, ge=0, le=12)
    weekly_hours: int = Field(default=40, ge=1, le=60)
    end_date: datetime | None = None
    notes: str | None = None
    # Identité du salarié (contrat légal)
    employee_civility: Civility | None = None
    employee_birth_date: datetime | None = None
    employee_cin: str | None = Field(default=None, max_length=30)
    employee_cin_issue_date: datetime | None = None
    employee_address: str | None = Field(default=None, max_length=300)


class ContractUpdate(BaseModel):
    contract_type: str | None = None
    position: str | None = Field(default=None, max_length=200)
    department: str | None = None
    salary: float | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    trial_period_months: int | None = Field(default=None, ge=0, le=12)
    weekly_hours: int | None = Field(default=None, ge=1, le=60)
    end_date: datetime | None = None
    notes: str | None = None
    employee_civility: Civility | None = None
    employee_birth_date: datetime | None = None
    employee_cin: str | None = Field(default=None, max_length=30)
    employee_cin_issue_date: datetime | None = None
    employee_address: str | None = Field(default=None, max_length=300)


class SendContractRequest(BaseModel):
    expires_in_days: int = Field(default=14, ge=1, le=90)
    message: str = Field(default="", max_length=1000)


class SignContractRequest(BaseModel):
    signer_name: str = Field(..., min_length=2, max_length=200)
    signature_image: str = Field(..., description="Signature manuscrite (data URI PNG)")
    consent: bool = Field(..., description="Consentement explicite à signer")


class DeclineContractRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ContractResponse(BaseModel):
    id: UUID
    application_id: UUID
    contract_type: str
    position: str
    department: str | None
    salary: float
    currency: str
    start_date: datetime | None
    trial_period_months: int
    weekly_hours: int
    end_date: datetime | None
    notes: str | None
    status: str
    sent_at: datetime | None
    expires_at: datetime | None
    signed_at: datetime | None
    signer_name: str | None
    certificate_id: str | None
    employee_id: UUID | None
    created_at: datetime
    employee_civility: str | None = None
    employee_birth_date: datetime | None = None
    employee_cin: str | None = None
    employee_cin_issue_date: datetime | None = None
    employee_address: str | None = None
    # Enrichissements
    candidate_name: str | None = None
    candidate_email: str | None = None
    job_title: str | None = None
    public_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PublicContractView(BaseModel):
    """Vue candidat (page publique de signature) — pas d'infos sensibles internes."""
    status: str
    contract_type: str
    position: str
    department: str | None
    salary: float
    currency: str
    start_date: datetime | None
    trial_period_months: int
    weekly_hours: int
    end_date: datetime | None
    candidate_name: str
    job_title: str
    company_name: str = "PIQBIT"
    expires_at: datetime | None
    signed_at: datetime | None
    certificate_id: str | None = None


class PendingContract(BaseModel):
    """
    Candidature ACCEPTÉE sans contrat : ce que le RH doit confirmer avant de
    générer le brouillon. Le salaire proposé porte sa provenance — le RH sait
    s'il confirme un montant négocié, la prétention du candidat ou l'offre.
    """
    application_id: UUID
    candidate_name: str
    candidate_email: str | None = None
    candidate_phone: str | None = None
    job_title: str
    suggested_salary: float | None
    #: "negotiation" | "expected_salary" | "offer_max" | "offer_min" | None
    salary_source: str | None
    expected_salary: float | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str = "TND"
    accepted_at: datetime | None = None
