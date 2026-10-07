"""
Interview invitation & slot models.

Workflow:
- RH proposes 1..5 slots when scheduling an interview → an InterviewInvitation
  is created with status=PENDING and a unique URL token. Each proposed slot
  becomes an InterviewSlot row linked to the invitation.
- Candidate clicks the public link (no login) and picks one slot. We mark
  the invitation CONFIRMED and the chosen slot is_selected=True.
- Sibling slots can be freed back to the pool because they live alongside
  the invitation and are no longer referenced as PROPOSED for any active link.
- RH can cancel an invitation at any time. A background sweep flips PENDING
  invitations past their expires_at to EXPIRED.
"""
import uuid
import enum
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey, Index, Boolean, func, Enum, Table
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class InvitationStatus(str, enum.Enum):
    PENDING = "PENDING"        # email sent, awaiting candidate
    CONFIRMED = "CONFIRMED"    # candidate picked a slot
    EXPIRED = "EXPIRED"        # 48h elapsed, no answer
    CANCELLED = "CANCELLED"    # RH cancelled before confirmation


# Membres de l'entretien : les personnes qui le mènent, et donc les seules à
# pouvoir l'évaluer. Un recruteur ne voit que les entretiens dont il est membre.
interview_members = Table(
    "interview_members",
    Base.metadata,
    Column("invitation_id", UUID(as_uuid=True),
           ForeignKey("interview_invitations.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True),
           ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class InterviewInvitation(Base):
    __tablename__ = "interview_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    # public URL token (URL-safe, ~32 chars)
    token = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(
        Enum(InvitationStatus, name="invitation_status"),
        default=InvitationStatus.PENDING,
        nullable=False,
        index=True,
    )
    message = Column(Text, nullable=True)  # optional RH note shown in email
    expires_at = Column(DateTime(timezone=True), nullable=False)

    confirmed_slot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("interview_slots.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Id de l'événement Google Calendar créé à la confirmation (sync optionnelle) —
    # permet la suppression de l'événement si l'entretien est annulé.
    google_event_id = Column(String(255), nullable=True)

    # Lien de visioconférence de l'entretien confirmé : Google Meet quand la
    # Espace créé par l'API Meet (OAuth utilisateur). Aucun repli : sans
    # compte Google lié, ce champ reste vide et aucun rappel ne part.
    # Figé à la confirmation, réutilisé dans l'email de confirmation et dans le
    # rappel « rejoindre maintenant » envoyé 8 min avant.
    meet_url = Column(String(500), nullable=True)
    # Horodatage d'envoi du rappel T-8 min — garde-fou d'idempotence : la boucle
    # de fond ne renvoie jamais un rappel déjà parti.
    meet_reminder_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Premier membre de l'entretien (voir `membres`). Conservé car il désigne
    # aussi le compte Google qui organise la réunion et l'invité de l'agenda.
    # Distinct de `created_by` (qui est le RH ayant planifié) : un manager
    # planifie souvent des entretiens que d'autres recruteurs conduisent.
    assigned_recruiter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Évaluation de CET entretien. La note vit sur la candidature
    # (`CandidateScore.interview_score`) ; la marquer ici distingue un second
    # entretien, encore à évaluer, du premier, déjà noté.
    evaluated_at = Column(DateTime(timezone=True), nullable=True)
    evaluated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Relations ──
    slots = relationship(
        "InterviewSlot",
        back_populates="invitation",
        cascade="all, delete-orphan",
        foreign_keys="InterviewSlot.invitation_id",
    )
    confirmed_slot = relationship(
        "InterviewSlot",
        foreign_keys=[confirmed_slot_id],
        post_update=True,
    )
    # Chargés avec l'invitation (selectin) : ils servent à chaque lecture —
    # visibilité, droit d'évaluer, destinataires des rappels.
    membres = relationship(
        "User",
        secondary=interview_members,
        lazy="selectin",
        order_by="User.full_name",
    )

    __table_args__ = (
        Index("ix_invitations_app_status", "application_id", "status"),
    )


class InterviewSlot(Base):
    __tablename__ = "interview_slots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invitation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("interview_invitations.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False)
    is_selected = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relations ──
    invitation = relationship(
        "InterviewInvitation",
        back_populates="slots",
        foreign_keys=[invitation_id],
    )

    __table_args__ = (
        Index("ix_slots_invitation", "invitation_id"),
        Index("ix_slots_start_selected", "start_at", "is_selected"),
    )
