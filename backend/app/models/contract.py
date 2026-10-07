import uuid
import enum
from sqlalchemy import (
    Column, String, Text, Float, Integer, DateTime, ForeignKey, Index, func, Enum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class ContractStatus(str, enum.Enum):
    DRAFT = "DRAFT"        # BROUILLON  — le RH complète les termes
    SENT = "SENT"          # ENVOYÉ     — lien de signature envoyé au candidat
    SIGNED = "SIGNED"      # SIGNÉ      — signé par le candidat (audit enregistré)
    ACTIVE = "ACTIVE"      # ACTIF      — employé créé, contrat en vigueur
    DECLINED = "DECLINED"  # REFUSÉ     — le candidat a refusé
    EXPIRED = "EXPIRED"    # EXPIRÉ     — délai de signature dépassé


class ContractType(str, enum.Enum):
    CDI = "CDI"
    CDD = "CDD"
    STAGE = "STAGE"
    ALTERNANCE = "ALTERNANCE"


class Contract(Base):
    """
    Contrat de travail issu d'une candidature acceptée. Ferme la boucle
    recrutement → RH : à la signature, un `Employee` est créé automatiquement.

    Signature électronique auto-hébergée (gratuite, sans API externe) :
    lien public à token (comme la confirmation d'entretien), signature
    manuscrite (image), et piste d'audit (nom, date UTC, IP, user-agent,
    empreinte SHA-256 des termes signés, identifiant de certificat).
    """
    __tablename__ = "contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )

    # ── Termes du contrat ─────────────────────────────────────────────────────
    contract_type = Column(
        Enum(ContractType, name="contract_type"), default=ContractType.CDI, nullable=False,
    )
    position = Column(String(200), nullable=False)          # prérempli depuis l'offre
    department = Column(String(100), nullable=True)
    salary = Column(Float, nullable=False)                  # mensuel brut, prérempli négociation
    currency = Column(String(8), default="TND", nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=True)
    trial_period_months = Column(Integer, default=3, nullable=False)  # période d'essai
    weekly_hours = Column(Integer, default=40, nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=True)         # CDD / stage
    notes = Column(Text, nullable=True)

    # ── Identité du salarié (pour le contrat légal tunisien) ──────────────────
    employee_civility = Column(String(5), nullable=True)              # « M. » / « Mme »
    employee_birth_date = Column(DateTime(timezone=True), nullable=True)
    employee_cin = Column(String(30), nullable=True)                  # carte d'identité
    employee_cin_issue_date = Column(DateTime(timezone=True), nullable=True)
    employee_address = Column(String(300), nullable=True)

    status = Column(
        Enum(ContractStatus, name="contract_status"),
        default=ContractStatus.DRAFT, nullable=False,
    )

    # ── Flux de signature ─────────────────────────────────────────────────────
    token = Column(String(64), nullable=True, unique=True, index=True)  # lien public
    sent_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    signed_at = Column(DateTime(timezone=True), nullable=True)
    signer_name = Column(String(200), nullable=True)
    signer_ip = Column(String(45), nullable=True)
    signer_user_agent = Column(String(400), nullable=True)
    signature_image = Column(Text, nullable=True)     # data URI PNG (signature manuscrite)
    document_hash = Column(String(64), nullable=True)  # SHA-256 des termes signés
    certificate_id = Column(String(40), nullable=True)  # identifiant de certificat lisible

    declined_at = Column(DateTime(timezone=True), nullable=True)
    decline_reason = Column(Text, nullable=True)

    # ── Boucle RH : employé créé à l'activation ───────────────────────────────
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    application = relationship("Application")

    __table_args__ = (
        Index("ix_contracts_status", "status"),
        Index("ix_contracts_application", "application_id"),
    )
