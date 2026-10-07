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
- etape_entretien(inv) -> l'étape affichée (à venir, à évaluer, évalué, …)
- peut_evaluer(inv, user) -> seuls les membres de l'entretien l'évaluent
"""
from __future__ import annotations
import secrets
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.config import settings
from app.models.interview import (
    InterviewInvitation,
    InterviewSlot,
    InvitationStatus,
    interview_members,
)
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


# Frontend base for the public confirmation page.
# Reads from env so it can be tuned per environment without rebuilds.
def _frontend_base_url() -> str:
    import os
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def entretien_termine(invitation: InterviewInvitation, maintenant: datetime | None = None) -> bool:
    """
    L'entretien confirmé a-t-il eu lieu ?

    Il n'existe pas de statut « terminé » : un entretien tenu reste CONFIRMED
    pour toujours. C'est donc la FIN de son créneau retenu qui dit s'il a eu
    lieu — comme pour le bouton d'évaluation côté écran.

    Faux pour une invitation sans créneau retenu : on ne sait pas quand elle a
    lieu, et la traiter comme passée laisserait ouvrir un doublon.
    """
    retenu = next((s for s in invitation.slots if s.is_selected), None)
    if retenu is None:
        return False
    # SQLite (tests) rend des dates sans fuseau ; PostgreSQL en rend avec.
    fin = retenu.end_at if retenu.end_at.tzinfo else retenu.end_at.replace(tzinfo=timezone.utc)
    return fin <= (maintenant or _now_utc())


# ── Étapes ──────────────────────────────────────────────────────────────────
#
# Le statut de l'invitation dit où en est l'ÉCHANGE avec le candidat ; l'étape
# dit où en est l'ENTRETIEN, et c'est elle que l'écran range en onglets.
#
#   PENDING                       → EN_ATTENTE  (le candidat n'a pas choisi)
#   PENDING passé l'échéance      → ABSENT      (aucune réponse sous 48 h)
#   EXPIRED                       → ABSENT
#   CANCELLED                     → ANNULE
#   CONFIRMED, créneau à venir    → A_VENIR     (en cours compris)
#   CONFIRMED, terminé, non noté  → A_EVALUER
#   CONFIRMED, terminé, noté      → EVALUE

ETAPE_A_VENIR = "A_VENIR"
ETAPE_A_EVALUER = "A_EVALUER"
ETAPE_EVALUE = "EVALUE"
ETAPE_EN_ATTENTE = "EN_ATTENTE"
ETAPE_ABSENT = "ABSENT"
ETAPE_ANNULE = "ANNULE"

#: Un entretien clos (absent, annulé) quitte la liste au-delà de ce délai.
JOURS_CONSERVATION_CLOS = 30

_STAFF = (UserRole.ADMIN, UserRole.RH, UserRole.RECRUTEUR)


def _utc(dt: datetime) -> datetime:
    # SQLite (tests) rend des dates sans fuseau ; PostgreSQL en rend avec.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def etape_entretien(invitation: InterviewInvitation, maintenant: datetime | None = None) -> str:
    """L'étape de l'entretien, celle qui détermine son onglet."""
    maintenant = maintenant or _now_utc()
    statut = invitation.status.value if hasattr(invitation.status, "value") else str(invitation.status)
    if statut == InvitationStatus.CANCELLED.value:
        return ETAPE_ANNULE
    if statut == InvitationStatus.EXPIRED.value:
        return ETAPE_ABSENT
    if statut == InvitationStatus.PENDING.value:
        # Le balayage de fond peut avoir du retard : l'échéance fait foi.
        return ETAPE_ABSENT if _utc(invitation.expires_at) <= maintenant else ETAPE_EN_ATTENTE
    if not entretien_termine(invitation, maintenant):
        return ETAPE_A_VENIR
    return ETAPE_EVALUE if invitation.evaluated_at else ETAPE_A_EVALUER


def est_membre(invitation: InterviewInvitation, user_id: UUID) -> bool:
    return any(m.id == user_id for m in invitation.membres)


def peut_evaluer(invitation: InterviewInvitation, user: User) -> bool:
    """
    Seuls les membres d'un entretien l'évaluent : ce sont eux qui l'ont mené.

    Un entretien sans aucun membre (planifié avant leur introduction, ou sans
    désignation) reste évaluable par le RH, l'administrateur et son créateur —
    sinon personne ne pourrait jamais le noter.
    """
    if user.is_superuser:
        return True
    if invitation.membres:
        return est_membre(invitation, user.id)
    return user.role in (UserRole.ADMIN, UserRole.RH) or user.id == invitation.created_by


def _normalize(dt: datetime) -> datetime:
    """Ensure tz-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def public_url_for(token: str) -> str:
    return f"{_frontend_base_url()}/interview/confirm/{token}"


#
# PAS DE REPLI DE VISIOCONFÉRENCE.
#
# Une salle Jitsi servait auparavant de secours quand Google Meet n'était pas
# disponible. Ce repli a été retiré : Google Meet est désormais le seul
# fournisseur.
#
# La conséquence doit être comprise plutôt que subie. Si le compte Google n'est
# pas lié, ou si l'API refuse, il n'y a **aucun lien** — ni sur la carte, ni
# dans le rappel envoyé avant l'entretien. L'API répond alors par une erreur
# explicite, et l'interface propose de connecter Google Meet. C'est un choix :
# mieux vaut une absence visible, qui se corrige, qu'un lien de secours que
# personne n'attendait et sur lequel le candidat se retrouve seul.
#


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
        assigned_recruiter_id: UUID | None = None,
        member_ids: list[UUID] | None = None,
        meet_url: str | None = None,
    ) -> InterviewInvitation:
        """
        Create a new invitation. Business rules:
          - If a CONFIRMED invitation already exists AND its interview has not
            taken place yet, refuse (409). The RH must cancel it first if they
            want to re-plan. Once it has taken place it stays on file as
            history and no longer blocks: a second interview is common.
          - If a PENDING invitation exists (candidate hasn't picked yet),
            supersede it: mark as CANCELLED, then create the new one. This
            lets the RH adjust the proposed slots without manual cleanup.
          - CANCELLED / EXPIRED invitations are ignored — re-planning is fine.
        """
        result = await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(
                InterviewInvitation.application_id == application_id,
                InterviewInvitation.status.in_(
                    [InvitationStatus.PENDING, InvitationStatus.CONFIRMED]
                ),
            )
        )
        existing_active = result.scalars().all()
        maintenant = _now_utc()
        for inv in existing_active:
            if inv.status == InvitationStatus.CONFIRMED:
                if entretien_termine(inv, maintenant):
                    continue   # il a eu lieu : il reste au dossier, sans rien bloquer
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Un entretien est déjà confirmé pour cette candidature et n'a "
                        "pas encore eu lieu. Annulez-le d'abord pour pouvoir replanifier."
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

        # Membres : dédoublonnés, dans l'ordre choisi. Seul le personnel de
        # recrutement actif peut mener un entretien.
        ids = list(dict.fromkeys([*(member_ids or []),
                                  *([assigned_recruiter_id] if assigned_recruiter_id else [])]))
        membres: list[User] = []
        if ids:
            trouves = {
                u.id: u for u in (await db.execute(
                    select(User).where(User.id.in_(ids), User.is_active.is_(True),
                                       User.role.in_(_STAFF))
                )).scalars().all()
            }
            if len(trouves) != len(ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Un des membres choisis n'est pas un recruteur actif.",
                )
            membres = [trouves[i] for i in ids]

        token = secrets.token_urlsafe(32)
        invitation = InterviewInvitation(
            application_id=application_id,
            token=token,
            status=InvitationStatus.PENDING,
            message=message or None,
            expires_at=_now_utc() + timedelta(hours=expires_in_hours),
            created_by=created_by,
            assigned_recruiter_id=membres[0].id if membres else None,
            membres=membres,
            # Lien figé dès la planification quand le RH en a généré un. La
            # confirmation ne l'écrase pas : c'est ce lien-là qui a pu être
            # communiqué, et en changer romprait la parole donnée.
            meet_url=meet_url or None,
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
        recruiter_id: UUID | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Invitations pour l'écran des entretiens.

        `recruiter_id` restreint aux entretiens dont cette personne est membre.
        Sans candidature précise, les entretiens clos (absent, annulé) depuis
        plus de `JOURS_CONSERVATION_CLOS` jours sont écartés : ils encombrent
        la liste sans plus rien demander.
        """
        query = (
            select(InterviewInvitation, Application, Candidate, User, JobOffer,
                   CandidateScore.interview_score)
            .join(Application, InterviewInvitation.application_id == Application.id)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(User, Candidate.user_id == User.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .outerjoin(CandidateScore, CandidateScore.application_id == Application.id)
            .options(selectinload(InterviewInvitation.slots))
            .order_by(InterviewInvitation.created_at.desc())
            .limit(limit)
        )
        if status_filter:
            query = query.where(InterviewInvitation.status == status_filter)
        if application_id:
            query = query.where(InterviewInvitation.application_id == application_id)
        else:
            limite = _now_utc() - timedelta(days=JOURS_CONSERVATION_CLOS)
            query = query.where(or_(
                InterviewInvitation.status.in_([InvitationStatus.PENDING, InvitationStatus.CONFIRMED]),
                func.coalesce(InterviewInvitation.cancelled_at, InterviewInvitation.expires_at) >= limite,
            ))
        if recruiter_id:
            query = query.where(InterviewInvitation.id.in_(self._invitations_du_membre(recruiter_id)))

        result = await db.execute(query)
        items: list[dict] = []
        for inv, app, candidate, user, job, note in result.all():
            items.append({
                "invitation": inv,
                "candidate_name": candidate.full_name,
                "candidate_email": user.email,
                "job_title": job.title,
                "job_offer_id": job.id,
                "application_status": app.status,
                "interview_score": note,
                "public_url": public_url_for(inv.token),
            })
        return items

    @staticmethod
    def _invitations_du_membre(user_id: UUID):
        return select(interview_members.c.invitation_id).where(interview_members.c.user_id == user_id)

    async def note_entretien(self, db: AsyncSession, application_id: UUID) -> float | None:
        return (await db.execute(
            select(CandidateScore.interview_score)
            .where(CandidateScore.application_id == application_id)
        )).scalar_one_or_none()

    # ── Évaluation ─────────────────────────────────────────────

    async def entretien_a_evaluer(
        self, db: AsyncSession, application_id: UUID
    ) -> InterviewInvitation | None:
        """Le dernier entretien TENU de la candidature : celui que la note concerne."""
        confirmes = (await db.execute(
            select(InterviewInvitation)
            .options(selectinload(InterviewInvitation.slots))
            .where(InterviewInvitation.application_id == application_id,
                   InterviewInvitation.status == InvitationStatus.CONFIRMED)
        )).scalars().all()
        maintenant = _now_utc()
        tenus = [i for i in confirmes if entretien_termine(i, maintenant)]
        if not tenus:
            return None
        return max(tenus, key=lambda i: _utc(next(s for s in i.slots if s.is_selected).end_at))

    async def verifier_droit_evaluation(
        self, db: AsyncSession, application_id: UUID, user: User
    ) -> InterviewInvitation | None:
        """
        403 si l'appelant n'est pas membre de l'entretien à évaluer.

        Une candidature sans entretien tenu garde l'ancienne règle (le rôle
        suffit) : le RH peut noter un échange mené hors de l'outil.
        """
        entretien = await self.entretien_a_evaluer(db, application_id)
        if entretien is not None and not peut_evaluer(entretien, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seuls les membres de l'entretien peuvent l'évaluer.",
            )
        return entretien

    async def marquer_evaluation(
        self, db: AsyncSession, application_id: UUID, user: User, *, evalue: bool
    ) -> None:
        """Marque (ou démarque, si la note est effacée) le dernier entretien tenu."""
        entretien = await self.entretien_a_evaluer(db, application_id)
        if entretien is None:
            return
        entretien.evaluated_at = _now_utc() if evalue else None
        entretien.evaluated_by = user.id if evalue else None
        await db.flush()

    # ── Calendar ──────────────────────────────────────────────

    async def build_calendar(
        self,
        db: AsyncSession,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        state_filter: str | None = None,
        member_id: UUID | None = None,
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
        if member_id:
            query = query.where(InterviewInvitation.id.in_(self._invitations_du_membre(member_id)))

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
    ) -> list[tuple[str, str | None]]:
        """
        Adresses e-mail concernées par un entretien, en paires (rôle, adresse).

        - `candidate` : adresse du compte candidat.
        - `recruiter` : chaque membre de l'entretien. Ce sont eux qui le
          conduisent : les laisser hors des destinataires revenait à prévenir
          tout le monde sauf les intéressés.
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

        return [
            ("candidate", user.email),
            *(("recruiter", m.email) for m in inv.membres),
            ("rh", rh_email),
            ("superadmin", superadmin_email),
        ]

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
                    # Plus de repli : sans lien Meet, il n'y a rien à annoncer.
                    # On journalise et on passe — envoyer un rappel « rejoignez
                    # maintenant » sans adresse de réunion enverrait le candidat
                    # nulle part, ce qui est pire que de ne rien envoyer. Le
                    # rappel n'est PAS marqué comme parti : il repartira dès
                    # qu'un lien sera créé depuis la carte de l'entretien.
                    logger.warning(
                        "Rappel visio ignoré pour l'invitation %s : aucun lien "
                        "de réunion. Créer le lien depuis /admin/interviews.",
                        inv_id,
                    )
                    continue
                recipients = await self.resolve_interview_recipients(db, inv_id)

                start_local = _normalize(slot_start)
                minutes_before = max(int((start_local - now).total_seconds() // 60), 0)
                cand_name, job_title = candidate.full_name, job.title

                addressed: set[str] = set()
                for role, email in recipients:
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
