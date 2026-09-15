import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, Index, Boolean, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class JobOffer(Base):
    __tablename__ = "job_offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=False)
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    required_skills = Column(JSON, nullable=True, default=list)
    required_experience_years = Column(Float, nullable=True)
    required_education_level = Column(String(20), nullable=True)
    weight_skills = Column(Float, default=0.5, nullable=False)
    weight_experience = Column(Float, default=0.3, nullable=False)
    weight_education = Column(Float, default=0.2, nullable=False)

    # ── Conditions du poste ─────────────────────────────────────────────
    # ON_SITE | HYBRID | REMOTE
    work_mode = Column(String(20), nullable=True)
    # Liste de CDI | CDD | SIVP | STAGE | FREELANCE.
    #
    # Une offre peut légitimement ouvrir sur plusieurs formes de contrat — un
    # même poste proposé « SIVP ou CDD » est courant en Tunisie. La colonne
    # porte donc un TABLEAU, là où elle ne gardait qu'une valeur unique et
    # obligeait à publier deux offres jumelles.
    contract_types = Column(JSON, nullable=True, default=list)
    # DRAFT | PUBLISHED | CLOSED — un brouillon n'est jamais visible côté
    # candidat. `server_default` couvre les lignes créées avant ce champ :
    # elles étaient déjà visibles, donc PUBLISHED est la valeur qui préserve
    # le comportement existant.
    status = Column(String(20), nullable=False, server_default="PUBLISHED", default="PUBLISHED", index=True)
    # Passée cette date l'offre disparaît du frontoffice (NULL = sans limite).
    expires_at = Column(DateTime(timezone=True), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    applications = relationship("Application", back_populates="job_offer", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_job_offers_active_created", "is_active", "created_at"),)


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(30), nullable=True)
    # CV « de référence » du candidat, géré depuis son espace. Facultatif :
    # l'inscription n'en exige pas, il peut être déposé plus tard.
    cv_path = Column(String(500), nullable=True)
    cv_filename = Column(String(255), nullable=True)   # nom d'origine, pour l'affichage
    cv_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="candidate")
    applications = relationship("Application", back_populates="candidate", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_candidates_user_id", "user_id"),)


class SavedJob(Base):
    """A job offer bookmarked by a user (frontoffice "Offres sauvegardées")."""
    __tablename__ = "saved_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    job_offer_id = Column(UUID(as_uuid=True), ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job_offer = relationship("JobOffer")
    __table_args__ = (
        Index("ix_saved_jobs_user_job", "user_id", "job_offer_id", unique=True),
    )


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    job_offer_id = Column(UUID(as_uuid=True), ForeignKey("job_offers.id"), nullable=False)
    # Copie figée du CV au moment du dépôt (cf. app/services/cv_storage.py) :
    # remplacer son CV de profil ne doit pas réécrire les dossiers déjà déposés.
    cv_file_path = Column(String(500), nullable=False)
    status = Column(String(50), default="PENDING", nullable=False)
    # Prétention salariale annoncée par le candidat POUR CETTE OFFRE, en TND
    # mensuels bruts. Facultative : elle est demandée après l'envoi du dossier
    # et peut être passée, une candidature ne doit pas se perdre sur un chiffre.
    expected_salary = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    candidate = relationship("Candidate", back_populates="applications")
    job_offer = relationship("JobOffer", back_populates="applications")
    __table_args__ = (
        Index("ix_applications_candidate_job", "candidate_id", "job_offer_id"),
        Index("ix_applications_status", "status"),
    )
