"""
Interview invitation endpoints.

Public (no auth):
  GET    /interview/confirm/{token}          → fetch invitation context for the page
  POST   /interview/confirm/{token}          → candidate picks one slot

RH-side (auth required):
  GET    /interview/invitations              → list invitations (with filters)
  GET    /interview/invitations/{id}         → single invitation details
  POST   /interview/invitations/{id}/cancel  → cancel an invitation
  GET    /interview/calendar                 → aggregated slot calendar
"""
from datetime import datetime
from typing import Annotated
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.interview import InvitationStatus
from app.schemas.interview import (
    ConfirmSlotRequest,
    CancelInvitationRequest,
    InvitationResponse,
    InterviewSlotResponse,
    PublicInvitationView,
    CalendarSlot,
    CalendarResponse,
)
from app.services.interview_service import interview_service, public_url_for
from app.services.email_service import (
    send_interview_confirmation_candidate,
    send_interview_notification_rh,
    send_interview_cancellation,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def _sync_confirmed_to_google(invitation_id: UUID, db: AsyncSession | None = None) -> str | None:
    """
    Pousse l'entretien confirmé vers Google Calendar (si configuré) et stocke
    l'`eventId` sur l'invitation. Best-effort : ne lève jamais.

    - Appelée en `BackgroundTask` (après confirmation candidat) : pas de
      session de requête disponible → on en ouvre une dédiée.
    - Appelée directement par l'endpoint de resync manuel : on réutilise la
      session de la requête (`db`) pour rester cohérent avec les autres
      lectures/écritures de cet appel (et pour que les tests avec DB de test
      injectée fonctionnent correctement).
    """
    import asyncio
    from app.integrations.google_calendar import google_calendar_client

    if not google_calendar_client.available:
        return None

    async def _run(session: AsyncSession) -> str | None:
        inv, app, candidate, user, job = await interview_service.get_invitation_context(
            session, invitation_id
        )
        slot = inv.confirmed_slot
        if not slot or inv.google_event_id:
            return inv.google_event_id

        # httpx sync + refresh de token sync → thread pour ne pas bloquer la loop.
        event_id = await asyncio.to_thread(
            google_calendar_client.create_interview_event,
            summary=f"Entretien PIQBIT — {candidate.full_name} ({job.title})",
            description=(
                f"Candidat : {candidate.full_name} <{user.email}>\n"
                f"Poste : {job.title}\n"
                f"Invitation : {public_url_for(inv.token)}"
            ),
            start_at=slot.start_at,
            end_at=slot.end_at,
            attendee_email=user.email,
        )
        if event_id:
            inv.google_event_id = event_id
            await session.commit()
        return event_id

    try:
        if db is not None:
            return await _run(db)
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            return await _run(session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Google Calendar sync failed for invitation {invitation_id}: {exc}")
        return None


async def _send_test_after_confirmation(application_id: UUID) -> None:
    """
    Le candidat vient de confirmer sa présence : s'il n'a encore jamais reçu de
    test pour cette candidature, il en reçoit un maintenant — à faire AVANT
    l'entretien plutôt qu'en salle d'attente.

    Best-effort et silencieux, comme la synchro Google : une raison de ne pas
    envoyer (pas de vivier pour l'offre, score sous le seuil, test déjà passé)
    n'est pas une erreur, et un échec ici ne doit jamais remettre en cause une
    confirmation déjà acquise. Le RH garde la main : un test déjà envoyé,
    en cours ou terminé n'est jamais recouvert.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.recruitment import Application, Candidate, JobOffer
    from app.services.assessment_service import assessment_service
    from app.services.email_service import send_technical_test_invitation
    from sqlalchemy import select

    try:
        async with AsyncSessionLocal() as session:
            test_session = await assessment_service.auto_send_test_for_confirmed_interview(
                session, application_id,
            )
            if not test_session:
                return
            # Figé avant le commit : après, un accès ORM rechargerait hors greenlet.
            envoi = dict(
                token=test_session.token,
                question_count=test_session.question_count,
                duration_minutes=test_session.duration_minutes,
                expires_at=test_session.link_expires_at,
            )
            destinataire = (await session.execute(
                select(User.email, Candidate.full_name, JobOffer.title)
                .select_from(Application)
                .join(Candidate, Application.candidate_id == Candidate.id)
                .join(User, Candidate.user_id == User.id)
                .join(JobOffer, Application.job_offer_id == JobOffer.id)
                .where(Application.id == application_id)
            )).first()
            await session.commit()

        if destinataire:
            await send_technical_test_invitation(
                to_email=destinataire[0], candidate_name=destinataire[1],
                job_title=destinataire[2], **envoi,
            )
            logger.info("Test technique envoyé automatiquement (candidature %s)", application_id)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(f"Envoi automatique du test échoué pour {application_id}: {exc}")


async def _delete_google_event(event_id: str) -> None:
    """Supprime l'événement Google d'un entretien annulé (best-effort)."""
    import asyncio
    from app.integrations.google_calendar import google_calendar_client

    if google_calendar_client.available and event_id:
        await asyncio.to_thread(google_calendar_client.delete_event, event_id)


def _serialize_slot(slot) -> InterviewSlotResponse:
    return InterviewSlotResponse(
        id=slot.id,
        invitation_id=slot.invitation_id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        is_selected=slot.is_selected,
    )


def _status_str(inv) -> str:
    """Handle SQLAlchemy Enum column returning enum or string."""
    return inv.status.value if hasattr(inv.status, "value") else str(inv.status)


# ════════════════════════════════════════════════════════════════════
#  PUBLIC ENDPOINTS — no authentication, accessed via token
# ════════════════════════════════════════════════════════════════════

@router.get("/confirm/{token}", response_model=PublicInvitationView)
async def get_public_invitation(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the data needed to render the public confirmation page."""
    inv, app, candidate, user, job = await interview_service.get_invitation_context_by_token(db, token)

    confirmed_slot = None
    if inv.confirmed_slot_id:
        confirmed_slot = next((s for s in inv.slots if s.id == inv.confirmed_slot_id), None)

    return PublicInvitationView(
        status=_status_str(inv),
        expires_at=inv.expires_at,
        message=inv.message,
        candidate_name=candidate.full_name,
        job_title=job.title,
        job_description=job.description,
        slots=[_serialize_slot(s) for s in sorted(inv.slots, key=lambda x: x.start_at)],
        confirmed_slot=_serialize_slot(confirmed_slot) if confirmed_slot else None,
    )


@router.post("/confirm/{token}", response_model=PublicInvitationView)
async def confirm_invitation(
    token: str,
    body: ConfirmSlotRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Candidate picks a slot. Sends confirmation email + ICS, notifies RH."""
    invitation, slot = await interview_service.confirm_slot(db, token, body.slot_id)
    await db.commit()

    # Get full context for emails
    inv, app, candidate, user, job = await interview_service.get_invitation_context(db, invitation.id)

    # Candidate confirmation + ICS
    background_tasks.add_task(
        send_interview_confirmation_candidate,
        to_email=user.email,
        candidate_name=candidate.full_name,
        job_title=job.title,
        slot_start=slot.start_at,
        slot_end=slot.end_at,
    )

    # RH notification (creator if known, otherwise first admin email)
    rh_email = None
    creator = None
    if invitation.created_by:
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.id == invitation.created_by))
        creator = result.scalar_one_or_none()
        if creator:
            rh_email = creator.email
    if rh_email:
        background_tasks.add_task(
            send_interview_notification_rh,
            to_email=rh_email,
            candidate_name=candidate.full_name,
            candidate_email=user.email,
            job_title=job.title,
            slot_start=slot.start_at,
            slot_end=slot.end_at,
        )

    # Notification in-app au RH créateur de l'invitation (le candidat confirme
    # son propre créneau : il n'y a pas d'« acteur RH » ici, donc pas de
    # notification admin — seul le RH créateur est concerné).
    if creator:
        from app.services.notification_service import notification_service
        await notification_service.notify_user(
            db, recipient_id=creator.id, type="INTERVIEW_CONFIRMED",
            title="Entretien confirmé",
            message=f"{candidate.full_name} a confirmé son créneau pour « {job.title} ».",
            link="/admin/interviews",
        )
        await db.commit()

    # Sync Google Calendar (best-effort, seulement si configuré).
    background_tasks.add_task(_sync_confirmed_to_google, invitation.id)

    # Test technique à faire avant l'entretien (best-effort, cf. la fonction).
    background_tasks.add_task(_send_test_after_confirmation, app.id)

    logger.info(f"Interview confirmed: invitation={invitation.id}, slot={slot.id}, candidate={user.email}")

    return PublicInvitationView(
        status=_status_str(invitation),
        expires_at=invitation.expires_at,
        message=invitation.message,
        candidate_name=candidate.full_name,
        job_title=job.title,
        job_description=job.description,
        slots=[_serialize_slot(s) for s in sorted(invitation.slots, key=lambda x: x.start_at)],
        confirmed_slot=_serialize_slot(slot),
    )


# ════════════════════════════════════════════════════════════════════
#  RH ENDPOINTS — authenticated, RH staff/manager/admin only
# ════════════════════════════════════════════════════════════════════

@router.get(
    "/applications/{application_id}/active-invitation",
    dependencies=[Depends(require("interviews", "read"))],
)
async def get_active_invitation_for_application(
    application_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Quick lookup: is there a live PENDING/CONFIRMED invitation for this
    application? Used by the RH UI to grey-out the 'Planifier Entretien'
    button. Returns `{ active: false }` when nothing exists (200, not 404).
    """
    inv = await interview_service.get_active_invitation(db, application_id)
    if inv is None:
        return {"active": False}
    return {
        "active": True,
        "id": str(inv.id),
        "status": _status_str(inv),
        "token": inv.token,
        "expires_at": inv.expires_at,
        "confirmed_slot_id": str(inv.confirmed_slot_id) if inv.confirmed_slot_id else None,
        "confirmed_at": inv.confirmed_at,
        "slots": [
            {
                "id": str(s.id),
                "start_at": s.start_at,
                "end_at": s.end_at,
                "is_selected": s.is_selected,
            }
            for s in sorted(inv.slots, key=lambda x: x.start_at)
        ],
        "public_url": public_url_for(inv.token),
    }


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    dependencies=[Depends(require("interviews", "read"))],
)
async def list_invitations(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status",
                                       description="PENDING / CONFIRMED / EXPIRED / CANCELLED"),
    application_id: UUID | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
):
    items = await interview_service.list_invitations(
        db, status_filter=status_filter, application_id=application_id, limit=limit
    )
    out: list[InvitationResponse] = []
    for item in items:
        inv = item["invitation"]
        out.append(InvitationResponse(
            id=inv.id,
            application_id=inv.application_id,
            token=inv.token,
            status=_status_str(inv),
            message=inv.message,
            expires_at=inv.expires_at,
            confirmed_slot_id=inv.confirmed_slot_id,
            confirmed_at=inv.confirmed_at,
            cancelled_at=inv.cancelled_at,
            cancellation_reason=inv.cancellation_reason,
            created_at=inv.created_at,
            updated_at=inv.updated_at,
            slots=[_serialize_slot(s) for s in sorted(inv.slots, key=lambda x: x.start_at)],
            candidate_name=item["candidate_name"],
            candidate_email=item["candidate_email"],
            job_title=item["job_title"],
            public_url=item["public_url"],
        ))
    return out


@router.get(
    "/invitations/{invitation_id}",
    response_model=InvitationResponse,
    dependencies=[Depends(require("interviews", "read"))],
)
async def get_invitation(
    invitation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    inv, app, candidate, user, job = await interview_service.get_invitation_context(db, invitation_id)
    return InvitationResponse(
        id=inv.id,
        application_id=inv.application_id,
        token=inv.token,
        status=_status_str(inv),
        message=inv.message,
        expires_at=inv.expires_at,
        confirmed_slot_id=inv.confirmed_slot_id,
        confirmed_at=inv.confirmed_at,
        cancelled_at=inv.cancelled_at,
        cancellation_reason=inv.cancellation_reason,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        slots=[_serialize_slot(s) for s in sorted(inv.slots, key=lambda x: x.start_at)],
        candidate_name=candidate.full_name,
        candidate_email=user.email,
        job_title=job.title,
        public_url=public_url_for(inv.token),
    )


@router.post(
    "/invitations/{invitation_id}/cancel",
    response_model=InvitationResponse,
    dependencies=[Depends(require("interviews", "write"))],
)
async def cancel_invitation(
    invitation_id: UUID,
    body: CancelInvitationRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    invitation = await interview_service.cancel_invitation(db, invitation_id, reason=body.reason)
    await db.commit()

    # Notify candidate
    inv, app, candidate, user, job = await interview_service.get_invitation_context(db, invitation.id)
    background_tasks.add_task(
        send_interview_cancellation,
        to_email=user.email,
        candidate_name=candidate.full_name,
        job_title=job.title,
        reason=body.reason,
    )

    # Retirer l'événement Google Calendar si l'entretien y avait été poussé.
    if inv.google_event_id:
        background_tasks.add_task(_delete_google_event, inv.google_event_id)

    from app.services.notification_service import notification_service
    await notification_service.notify_user(
        db, recipient_id=user.id, type="INTERVIEW_CANCELLED",
        title="Entretien annulé",
        message=f"Votre entretien pour « {job.title} » a été annulé.",
        link="/frontoffice/applications",
    )
    await notification_service.notify_admins(
        db, actor=current_user, type="INTERVIEW_CANCELLED",
        title="Entretien annulé",
        message=(f"{current_user.full_name or current_user.username} a annulé l'entretien "
                 f"de {candidate.full_name} ({job.title})."),
        link="/admin/interviews",
    )
    await db.commit()

    return InvitationResponse(
        id=inv.id,
        application_id=inv.application_id,
        token=inv.token,
        status=_status_str(inv),
        message=inv.message,
        expires_at=inv.expires_at,
        confirmed_slot_id=inv.confirmed_slot_id,
        confirmed_at=inv.confirmed_at,
        cancelled_at=inv.cancelled_at,
        cancellation_reason=inv.cancellation_reason,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        slots=[_serialize_slot(s) for s in sorted(inv.slots, key=lambda x: x.start_at)],
        candidate_name=candidate.full_name,
        candidate_email=user.email,
        job_title=job.title,
        public_url=public_url_for(inv.token),
    )


@router.get(
    "/calendar",
    response_model=CalendarResponse,
    dependencies=[Depends(require("interviews", "read"))],
)
async def get_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    state: str | None = Query(None, description="AVAILABLE / PROPOSED / RESERVED"),
):
    items_raw = await interview_service.build_calendar(
        db, date_from=date_from, date_to=date_to, state_filter=state
    )
    items = [CalendarSlot(**item) for item in items_raw]
    return CalendarResponse(total=len(items), items=items)


# ════════════════════════════════════════════════════════════════════
#  GOOGLE CALENDAR & ICS — RH only
# ════════════════════════════════════════════════════════════════════

@router.get(
    "/google-status",
    dependencies=[Depends(require("interviews", "read"))],
)
async def google_calendar_status():
    """État de l'intégration Google Calendar (configurée ou non, et pourquoi)."""
    from app.integrations.google_calendar import google_calendar_client
    return google_calendar_client.status


@router.post(
    "/invitations/{invitation_id}/sync-google",
    dependencies=[Depends(require("interviews", "write"))],
)
async def sync_invitation_to_google(
    invitation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    (Re)pousse manuellement un entretien **confirmé** vers Google Calendar.
    Utile si la sync automatique a échoué ou a été activée après coup.
    """
    from app.integrations.google_calendar import google_calendar_client

    if not google_calendar_client.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar non configuré "
                   "(GOOGLE_CALENDAR_CREDENTIALS_FILE / GOOGLE_CALENDAR_ID).",
        )

    inv, app, candidate, user, job = await interview_service.get_invitation_context(db, invitation_id)
    if _status_str(inv) != "CONFIRMED" or not inv.confirmed_slot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seuls les entretiens confirmés peuvent être synchronisés.",
        )
    if inv.google_event_id:
        return {"synced": True, "google_event_id": inv.google_event_id, "already": True}

    event_id = await _sync_confirmed_to_google(invitation_id, db)
    if not event_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="La création de l'événement Google Calendar a échoué (voir logs).",
        )
    return {"synced": True, "google_event_id": event_id, "already": False}


@router.get(
    "/invitations/{invitation_id}/ics",
    dependencies=[Depends(require("interviews", "read"))],
)
async def download_invitation_ics(
    invitation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Télécharge le fichier **.ics** (RFC 5545) de l'entretien confirmé —
    importable dans Google Calendar, Outlook, Apple Calendar sans aucune API.
    """
    from fastapi import Response
    from app.services.email_service import build_ics

    inv, app, candidate, user, job = await interview_service.get_invitation_context(db, invitation_id)
    if _status_str(inv) != "CONFIRMED" or not inv.confirmed_slot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seuls les entretiens confirmés ont un fichier calendrier.",
        )
    slot = inv.confirmed_slot
    ics_bytes = build_ics(
        summary=f"Entretien PIQBIT — {candidate.full_name} ({job.title})",
        description=f"Candidat : {candidate.full_name} <{user.email}> — Poste : {job.title}",
        start_at=slot.start_at,
        end_at=slot.end_at,
        attendee_email=user.email,
    )
    safe = candidate.full_name.replace(" ", "_")[:40]
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="entretien_{safe}.ics"'},
    )
