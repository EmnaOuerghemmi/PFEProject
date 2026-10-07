"""
Vivier de candidats « en réserve ».

Un candidat solide mais non retenu pour l'offre à laquelle il a postulé est
placé en réserve depuis l'aide à la décision : sa candidature passe à
`ON_HOLD`, il en est informé par e-mail, et il est invité automatiquement dès
qu'une offre ouverte correspond à son profil.

Deux tables :

- `talent_pool_entries` : QUI est en réserve, depuis quand, et sur quelle
  candidature. L'appartenance au vivier reste dérivée du statut : une entrée
  dont la candidature a quitté `ON_HOLD` (acceptée, rejetée…) n'est plus lue.
- `talent_pool_invitations` : à quelles offres le candidat a déjà été invité.
  Une offre n'est jamais proposée deux fois au même candidat.
"""
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class TalentPoolEntry(Base):
    __tablename__ = "talent_pool_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"),
                            nullable=False, unique=True)
    reserved_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reserved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (Index("ix_talent_pool_entries_candidate", "candidate_id"),)


class TalentPoolInvitation(Base):
    __tablename__ = "talent_pool_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_offer_id = Column(UUID(as_uuid=True), ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False)
    #: Compatibilité calculée au moment de l'invitation (0–1).
    compatibility = Column(Float, nullable=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("candidate_id", "job_offer_id", name="uq_talent_pool_invitation"),
        Index("ix_talent_pool_invitations_candidate_sent", "candidate_id", "sent_at"),
    )
