"""
Interview lifecycle service.

Public API:
- create_invitation(db, application_id, slots, message, expires_in_hours, created_by)
- get_invitation_by_token(db, token)
- confirm_slot(db, token, slot_id) -> reserves the slot, notifies RH + candidate
- cancel_invitation(db, invitation_id, reason)
- list_invitations(db, status?, application_id?) -> RH list
- build_calendar(db, date_from, date_to, state_filter?)
- sweep_expired(db) -> background task, sets PENDING past expires_at to EXPIRED
"""
from __future__ import annotations
import secrets
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.interview import (
    InterviewInvitation,
    InterviewSlot,
    InvitationStatus,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


# Frontend base for the public confirmation page.
# Reads from env so it can be tuned per environment without rebuilds.
def _frontend_base_url() -> str:
    import os
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(dt: datetime) -> datetime:
    """Ensure tz-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def public_url_for(token: str) -> str:
    return f"{_frontend_base_url()}/interview/confirm/{token}"


def jitsi_url_for(token: str) -> str | None:
    """
    Salle Jitsi Meet de repli quand Google Meet n'est pas disponible.

    Le token de l'invitation (URL-safe, unique, non devinable) sert de nom de
    salle : un lien stable par entretien, sans compte ni configuration. `None`
    si le repli est explicitement désactivé (`INTERVIEW_MEET_FALLBACK_ENABLED`).
    """
    if not settings.INTERVIEW_MEET_FALLBACK_ENABLED:
        return None
    base = settings.INTERVIEW_MEET_JITSI_BASE.rstrip("/")
    return f"{base}/piqbit-{token}"


class InterviewService:

    # ── Creation ───────────────────────────────────────────────

    async def get_active_invitation(
        self, db: AsyncSession, application_id: UUID
    ) -> InterviewInvitation | None:
        """Return the live invitation (PENDING or CONFIRMED) for an application, if any."""
        result = await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(
                and_(
                    InterviewInvitation.application_id == application_id,
                    InterviewInvitation.status.in_(
                        [InvitationStatus.PENDING, InvitationStatus.CONFIRMED]
                    ),
                )
            )
            .order_by(InterviewInvitation.created_at.desc())
        )
        return result.scalars().first()

    async def create_invitation(
        self,
        db: AsyncSession,
        *,
        application_id: UUID,
        slots: list[datetime],
        duration_minutes: int = 30,
        message: str = "",
        expires_in_hours: int = 48,
        created_by: UUID | None = None,
    ) -> InterviewInvitation:
        """
        Create a new invitation. Business rules:
          - If a CONFIRMED invitation already exists, refuse (409). The RH
            must cancel it first if they want to re-plan.
          - If a PENDING invitation exists (candidate hasn't picked yet),
            supersede it: mark as CANCELLED, then create the new one. This
            lets the RH adjust the proposed slots without manual cleanup.
          - CANCELLED / EXPIRED invitations are ignored — re-planning is fine.
        """
        result = await db.execute(
            select(InterviewInvitation).where(
                InterviewInvitation.application_id == application_id,
                InterviewInvitation.status.in_(
                    [InvitationStatus.PENDING, InvitationStatus.CONFIRMED]
                ),
            )
        )
        existing_active = result.scalars().all()
        for inv in existing_active:
            if inv.status == InvitationStatus.CONFIRMED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Un entretien est déjà confirmé pour cette candidature. "
                        "Annulez-le d'abord pour pouvoir replanifier."
                    ),
                )
            # PENDING → supersede silently
            inv.status = InvitationStatus.CANCELLED
            inv.cancelled_at = _now_utc()
            inv.cancellation_reason = "Superseded by new invitation"
        await db.flush()

        if not slots:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="At least one slot is required")

        token = secrets.token_urlsafe(32)
        invitation = InterviewInvitation(
            application_id=application_id,
            token=token,
            status=InvitationStatus.PENDING,
            message=message or None,
            expires_at=_now_utc() + timedelta(hours=expires_in_hours),
            created_by=created_by,
        )
        db.add(invitation)
        await db.flush()

        delta = timedelta(minutes=duration_minutes)
        for raw in slots:
            start = _normalize(raw)
            db.add(InterviewSlot(
                invitation_id=invitation.id,
                start_at=start,
                end_at=start + delta,
                is_selected=False,
            ))
        await db.flush()
        await db.refresh(invitation, attribute_names=["slots"])
        return invitation

    # ── Read ───────────────────────────────────────────────────

    async def get_invitation_by_token(
        self, db: AsyncSession, token: str
    ) -> InterviewInvitation:
        result = await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(InterviewInvitation.token == token)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Invitation introuvable.")
        return invitation

    async def get_invitation_context(
        self, db: AsyncSession, invitation_id: UUID
    ) -> tuple[InterviewInvitation, Application, Candidate, User, JobOffer]:
        """Return invitation + joined application/candidate/user/job."""
        result = await db.execute(
            select(InterviewInvitation, Application, Candidate, User, JobOffer)
            .join(Application, InterviewInvitation.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(User, Candidate.user_id == User.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .options(selectinload(InterviewInvitation.slots))
            .where(InterviewInvitation.id == invitation_id)
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Invitation introuvable.")
        return row

    async def get_invitation_context_by_token(
        self, db: AsyncSession, token: str
    ) -> tuple[InterviewInvitation, Application, Candidate, User, JobOffer]:
        result = await db.execute(
            select(InterviewInvitation, Application, Candidate, User, JobOffer)
            .join(Application, InterviewInvitation.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(User, Candidate.user_id == User.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .options(selectinload(InterviewInvitation.slots))
            .where(InterviewInvitation.token == token)
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Invitation introuvable.")
        return row

    # ── Confirm ────────────────────────────────────────────────

    async def confirm_slot(
        self, db: AsyncSession, token: str, slot_id: UUID
    ) -> tuple[InterviewInvitation, InterviewSlot]:
        invitation = await self.get_invitation_by_token(db, token)

        if invitation.status == InvitationStatus.CONFIRMED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Cet entretien est déjà confirmé.")
        if invitation.status == InvitationStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_410_GONE,
                                detail="Cette invitation a été annulée.")
        if invitation.status == InvitationStatus.EXPIRED or invitation.expires_at < _now_utc():
            invitation.status = InvitationStatus.EXPIRED
            await db.flush()
            raise HTTPException(status_code=status.HTTP_410_GONE,
                                detail="Le lien d'invitation a expiré.")

        # Validate the slot belongs to this invitation
        slot = next((s for s in invitation.slots if s.id == slot_id), None)
        if not slot:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Créneau invalide pour cette invitation.")

        # Ensure no other invitation has a confirmed slot at the exact same time
        # (basic conflict prevention so two candidates don't get the same room).
        clash = await db.execute(
            select(InterviewSlot)
            .join(InterviewInvitation, InterviewSlot.invitation_id == InterviewInvitation.id)
            .where(and_(
                InterviewSlot.start_at == slot.start_at,
                InterviewSlot.is_selected.is_(True),
                InterviewInvitation.status == InvitationStatus.CONFIRMED,
                InterviewSlot.id != slot.id,
            ))
        )
        if clash.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ce créneau vient d'être réservé par un autre candidat. Choisissez-en un autre."
            )

        slot.is_selected = True
        invitation.status = InvitationStatus.CONFIRMED
        invitation.confirmed_slot_id = slot.id
        invitation.confirmed_at = _now_utc()
        await db.flush()
        return invitation, slot

    # ── Cancel ─────────────────────────────────────────────────

    async def cancel_invitation(
        self, db: AsyncSession, invitation_id: UUID, reason: str = ""
    ) -> InterviewInvitation:
        result = await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(InterviewInvitation.id == invitation_id)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Invitation introuvable.")
        if invitation.status == InvitationStatus.CANCELLED:
            return invitation
        invitation.status = InvitationStatus.CANCELLED
        invitation.cancelled_at = _now_utc()
        invitation.cancellation_reason = reason or None
        # release any selected slot
        for s in invitation.slots:
            s.is_selected = False
        await db.flush()
        return invitation

    # ── RH listing ─────────────────────────────────────────────

    async def list_invitations(
        self,
        db: AsyncSession,
        status_filter: str | None = None,
        application_id: UUID | None = None,
        limit: int = 200,
    ) -> list[dict]:
        query = (
            select(InterviewInvitation, Application, Candidate, User, JobOffer)
            .join(Application, InterviewInvitation.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(User, Candidate.user_id == User.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .options(selectinload(InterviewInvitation.slots))
            .order_by(InterviewInvitation.created_at.desc())
            .limit(limit)
        )
        if status_filter:
            query = query.where(InterviewInvitation.status == status_filter)
        if application_id:
            query = query.where(InterviewInvitation.application_id == application_id)

        result = await db.execute(query)
        items: list[dict] = []
        for inv, app, candidate, user, job in result.all():
            items.append({
                "invitation": inv,
                "candidate_name": candidate.full_name,
                "candidate_email": user.email,
                "job_title": job.title,
                "public_url": public_url_for(inv.token),
            })
        return items

    # ── Calendar ──────────────────────────────────────────────

    async def build_calendar(
        self,
        db: AsyncSession,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        state_filter: str | None = None,
    ) -> list[dict]:
        """
        Return every slot in the window with its computed state:
          - RESERVED  : invitation CONFIRMED + slot.is_selected
          - PROPOSED  : invitation PENDING (within expiry)
          - AVAILABLE : any other slot (cancelled/expired invites are "free")
        """
        query = (
            select(InterviewSlot, InterviewInvitation, Application, Candidate, JobOffer)
            .join(InterviewInvitation, InterviewSlot.invitation_id == InterviewInvitation.id)
            .join(Application, InterviewInvitation.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .order_by(InterviewSlot.start_at.asc())
        )
        if date_from:
            query = query.where(InterviewSlot.start_at >= date_from)
        if date_to:
            query = query.where(InterviewSlot.start_at <= date_to)

        result = await db.execute(query)
        rows = result.all()

        items: list[dict] = []
        now = _now_utc()
        for slot, inv, app, candidate, job in rows:
            if inv.status == InvitationStatus.CONFIRMED and slot.is_selected:
                state = "RESERVED"
            elif inv.status == InvitationStatus.PENDING and inv.expires_at > now:
                state = "PROPOSED"
            else:
                state = "AVAILABLE"

            if state_filter and state != state_filter:
                continue

            items.append({
                "id": slot.id,
                "invitation_id": inv.id,
                "application_id": app.id,
                "start_at": slot.start_at,
                "end_at": slot.end_at,
                "state": state,
                "candidate_name": candidate.full_name,
                "job_title": job.title,
                "invitation_status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                "confirmed_at": inv.confirmed_at,
                # Le lien visio n'a de sens que pour un créneau réservé.
                "meet_url": inv.meet_url if state == "RESERVED" else None,
            })
        return items

    # ── Sweeper ───────────────────────────────────────────────

    async def sweep_expired(self, db: AsyncSession) -> int:
        """Flip PENDING invitations past expires_at to EXPIRED. Returns count."""
        result = await db.execute(
            select(InterviewInvitation).where(
                and_(
                    InterviewInvitation.status == InvitationStatus.PENDING,
                    InterviewInvitation.expires_at < _now_utc(),
                )
            )
        )
        invitations = result.scalars().all()
        if not invitations:
            return 0
        for inv in invitations:
            inv.status = InvitationStatus.EXPIRED
        await db.commit()
        logger.info(f"Interview sweep: {len(invitations)} invitations expired")
        return len(invitations)

    # ── Destinataires ──────────────────────────────────────────

    async def resolve_interview_recipients(
        self, db: AsyncSession, invitation_id: UUID
    ) -> dict[str, str | None]:
        """
        Adresses e-mail concernées par un entretien : candidat, RH, superadmin.

        - `candidate` : adresse du compte candidat.
        - `rh` : créateur de l'invitation ; à défaut, premier administrateur
          actif (même repli que l'endpoint de confirmation).
        - `superadmin` : `SUPERADMIN_EMAIL` s'il est configuré, sinon premier
          compte `is_superuser` actif.

        Les valeurs sont dédupliquées par l'appelant (un RH qui est aussi le
        superadmin ne reçoit qu'un envoi).
        """
        inv, _app, _cand, user, _job = await self.get_invitation_context(db, invitation_id)

        rh_email: str | None = None
        if inv.created_by:
            creator = (
                await db.execute(select(User).where(User.id == inv.created_by))
            ).scalar_one_or_none()
            rh_email = creator.email if creator else None
        if not rh_email:
            admin = (
                await db.execute(
                    select(User)
                    .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
                    .order_by(User.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            rh_email = admin.email if admin else None

        superadmin_email: str | None = settings.SUPERADMIN_EMAIL or None
        if not superadmin_email:
            sa = (
                await db.execute(
                    select(User)
                    .where(User.is_superuser.is_(True), User.is_active.is_(True))
                    .order_by(User.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            superadmin_email = sa.email if sa else None

        return {"candidate": user.email, "rh": rh_email, "superadmin": superadmin_email}

    # ── Rappel « rejoindre maintenant » (T-N min) ──────────────

    async def send_due_meet_reminders(self, db: AsyncSession) -> int:
        """
        Envoie le rappel visio pour les entretiens confirmés dont l'heure de
        début tombe dans les `INTERVIEW_MEET_REMINDER_MINUTES` minutes à venir
        et qui n'ont pas encore reçu ce rappel.

        Appelée en boucle (toutes les 60 s) par une tâche de fond. Idempotente :
        `meet_reminder_sent_at` marque les rappels déjà partis. Best-effort par
        invitation — l'échec d'un envoi n'empêche pas les autres.
        """
        from sqlalchemy import update
        from app.services.email_service import send_interview_meet_link

        now = _now_utc()
        horizon = now + timedelta(minutes=settings.INTERVIEW_MEET_REMINDER_MINUTES)

        rows = await db.execute(
            select(
                InterviewInvitation.id,
                InterviewInvitation.token,
                InterviewInvitation.meet_url,
                InterviewSlot.start_at,
            )
            .join(InterviewSlot, InterviewInvitation.confirmed_slot_id == InterviewSlot.id)
            .where(
                and_(
                    InterviewInvitation.status == InvitationStatus.CONFIRMED,
                    InterviewInvitation.meet_reminder_sent_at.is_(None),
                    InterviewSlot.start_at > now,
                    InterviewSlot.start_at <= horizon,
                )
            )
        )
        # On matérialise en valeurs simples : le traitement d'une ligne fait
        # plusieurs allers-retours + commits, et un objet ORM survolé après un
        # commit (pool sans connexion persistante) rechargerait en synchrone.
        due = [(rid, token, meet_url, start) for rid, token, meet_url, start in rows.all()]
        if not due:
            return 0

        sent = 0
        for inv_id, token, meet_url, slot_start in due:
            try:
                _i, _app, candidate, _user, job = await self.get_invitation_context(db, inv_id)
                if not meet_url:
                    meet_url = jitsi_url_for(token)
                recipients = await self.resolve_interview_recipients(db, inv_id)

                start_local = _normalize(slot_start)
                minutes_before = max(int((start_local - now).total_seconds() // 60), 0)
                cand_name, job_title = candidate.full_name, job.title

                addressed: set[str] = set()
                for role, email in recipients.items():
                    if not email or email in addressed:
                        continue
                    addressed.add(email)
                    await send_interview_meet_link(
                        to_email=email,
                        recipient_role=role,
                        candidate_name=cand_name,
                        job_title=job_title,
                        slot_start=slot_start,
                        meet_url=meet_url,
                        minutes_before=minutes_before,
                    )

                await db.execute(
                    update(InterviewInvitation)
                    .where(InterviewInvitation.id == inv_id)
                    .values(meet_reminder_sent_at=now, meet_url=meet_url)
                )
                await db.commit()
                sent += 1
                logger.info(
                    "Interview meet reminder sent: invitation=%s recipients=%d",
                    inv_id, len(addressed),
                )
            except Exception as exc:  # pragma: no cover - best effort per row
                await db.rollback()
                logger.warning("Meet reminder failed for invitation %s: %s", inv_id, exc)

        return sent


interview_service = InterviewService()
