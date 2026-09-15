import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class Notification(Base):
    """
    In-app notification for a user (candidat ou staff RH/Admin).

    Deux flux alimentent cette table :
    - **Candidat** : changement de statut de candidature, entretien planifié /
      confirmé / annulé.
    - **RH → Admin** : toute création/action significative d'un compte
      RH/Recruteur (offre créée, employé ajouté, dépense budget,
      plan de carrière, négociation lancée, rapport généré...) notifie tous
      les comptes ADMIN.
    """
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Type machine-readable (ex. APPLICATION_STATUS_CHANGED, JOB_CREATED...)
    type = Column(String(60), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    # Route frontend relative à ouvrir au clic (ex. /admin/jobs).
    link = Column(String(300), nullable=True)

    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    recipient = relationship("User", foreign_keys=[recipient_id])
    actor = relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        Index("ix_notifications_recipient_read", "recipient_id", "is_read"),
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
    )
