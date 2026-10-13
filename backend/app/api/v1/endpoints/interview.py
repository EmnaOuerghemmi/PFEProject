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
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.interview import (
    ConfirmSlotRequest,
    CancelInvitationRequest,
    InterviewMemberResponse,
    InvitationResponse,
    InterviewSlotResponse,
    PublicInvitationView,
    CalendarSlot,
    CalendarResponse,
)
from app.core.config import settings
from app.services.interview_service import (
    est_membre,
    etape_entretien,
    interview_service,
    peut_evaluer,
    public_url_for,
)
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

        # Resolve recruiter email to add them as a calendar attendee.
        recruiter_email: str | None = None
        if inv.assigned_recruiter_id:
            from sqlalchemy import select as _sel
            from app.models.user import User as _User
            res = await session.execute(_sel(_User).where(_User.id == inv.assigned_recruiter_id))
            rec = res.scalar_one_or_none()
            if rec:
                recruiter_email = rec.email

        # httpx sync + refresh de token sync → thread pour ne pas bloquer la loop.
        event_id, meet_url = await asyncio.to_thread(
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
            recruiter_email=recruiter_email,
        )
        if event_id:
            inv.google_event_id = event_id
            # Le lien Meet rendu par Google n'était jusqu'ici pas conservé : le
            # jour où la délégation domaine est configurée, il était produit
            # puis jeté. On le garde — mais SANS écraser un lien déjà figé à la
            # planification, qui a pu être communiqué au candidat.
            if meet_url and not inv.meet_url:
                inv.meet_url = meet_url
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


async def _porteur_du_compte_meet(db: AsyncSession, inv) -> "User | None":
    """
    Qui crée la réunion, et donc qui en est l'organisateur.

    Un membre de l'entretien d'abord, dans l'ordre : ce sont eux qui le
    conduisent, et la portée `meetings.space.created` rattache l'espace au
    compte qui l'a créé. Le créateur de l'invitation ensuite, faute de mieux.
    """
    from sqlalchemy import select as _sel

    for identifiant in (*(m.id for m in inv.membres), inv.created_by):
        if not identifiant:
            continue
        personne = (
            await db.execute(_sel(User).where(User.id == identifiant))
        ).scalar_one_or_none()
        if personne and personne.google_meet_refresh_token:
            return personne
    return None


async def _creer_meet_apres_confirmation(invitation_id: UUID) -> None:
    """
    Crée l'espace Meet dès que le candidat a confirmé son créneau.

    POURQUOI ICI ET PAS À LA PLANIFICATION. À la confirmation, le créneau est
    connu : le lien peut partir avec la confirmation, il est utilisable, et
    aucun espace n'est créé pour une invitation qui expirera sans réponse.
    Générer à la planification produisait des salles pour des entretiens qui
    n'auraient jamais lieu.

    Automatique, et non déclenché par un bouton : un lien qu'on peut oublier
    de créer est un lien qui manquera le jour de l'entretien. Le bouton de la
    carte reste disponible en rattrapage.

    Best-effort : un échec ne remet pas en cause une confirmation acquise.
    """
    from app.db.session import AsyncSessionLocal
    from app.integrations.google_meet import google_meet_client

    try:
        async with AsyncSessionLocal() as session:
            inv, _app, _cand, _user, _job = await interview_service.get_invitation_context(
                session, invitation_id
            )
            if inv.meet_url:
                return  # déjà pourvu — ne jamais écraser un lien communiqué
            porteur = await _porteur_du_compte_meet(session, inv)
            if not porteur:
                return  # aucun compte Google lié : le repli suffira
            resultat = await asyncio.to_thread(
                google_meet_client.creer_espace, porteur.google_meet_refresh_token,
            )
            if resultat.get("meet_url"):
                inv.meet_url = resultat["meet_url"]
                await session.commit()
                logger.info("Espace Meet créé pour l'invitation %s", invitation_id)
            else:
                logger.info("Espace Meet non créé pour %s : %s",
                            invitation_id, resultat.get("error"))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Création Meet après confirmation échouée (%s) : %s",
                       invitation_id, exc)


async def _delete_google_event(event_id: str) -> None:
    """Supprime l'événement Google d'un entretien annulé (best-effort)."""
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


def _restreint_aux_membres(user: User) -> bool:
    """Un recruteur ne voit que les entretiens dont il est membre."""
    return user.role == UserRole.RECRUTEUR and not user.is_superuser


def _exiger_visibilite(inv, user: User) -> None:
    # 404 plutôt que 403 : ne rien laisser deviner d'un entretien qu'on ne voit pas.
    if _restreint_aux_membres(user) and not est_membre(inv, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation introuvable.")


def _reponse(
    inv, *, user: User, candidate_name: str | None, candidate_email: str | None,
    job_title: str | None, job_offer_id: UUID | None, application_status: str | None,
    interview_score: float | None,
) -> InvitationResponse:
    """Une seule façon de présenter une invitation, quelle que soit la route."""
    premier = inv.membres[0] if inv.membres else None
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
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_title=job_title,
        public_url=public_url_for(inv.token),
        meet_url=inv.meet_url,
        assigned_recruiter_id=premier.id if premier else None,
        assigned_recruiter_name=(premier.full_name or premier.email) if premier else None,
        assigned_recruiter_email=premier.email if premier else None,
        members=[InterviewMemberResponse(id=m.id, name=m.full_name or m.username or m.email, email=m.email)
                 for m in inv.membres],
        stage=etape_entretien(inv),
        can_evaluate=peut_evaluer(inv, user),
        evaluated_at=inv.evaluated_at,
        interview_score=interview_score,
        job_offer_id=job_offer_id,
        application_status=application_status,
    )


async def _reponse_contexte(db: AsyncSession, invitation_id: UUID, user: User) -> InvitationResponse:
    inv, app, candidate, cand_user, job = await interview_service.get_invitation_context(db, invitation_id)
    _exiger_visibilite(inv, user)
    return _reponse(
        inv, user=user, candidate_name=candidate.full_name, candidate_email=cand_user.email,
        job_title=job.title, job_offer_id=job.id, application_status=app.status,
        interview_score=await interview_service.note_entretien(db, app.id),
    )


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
        timezone=settings.APP_TIMEZONE,
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

    # Notify the assigned recruiter (preferred) and/or the invitation creator.
    from sqlalchemy import select as _select

    notified_ids: set = set()

    async def _notify_rh(rh_user: User) -> None:
        if rh_user.id in notified_ids:
            return
        notified_ids.add(rh_user.id)
        background_tasks.add_task(
            send_interview_notification_rh,
            to_email=rh_user.email,
            candidate_name=candidate.full_name,
            candidate_email=user.email,
            job_title=job.title,
            slot_start=slot.start_at,
            slot_end=slot.end_at,
        )
        from app.services.notification_service import notification_service
        await notification_service.notify_user(
            db, recipient_id=rh_user.id, type="INTERVIEW_CONFIRMED",
            title="Entretien confirmé",
            message=f"{candidate.full_name} a confirmé son créneau pour « {job.title} ».",
            link="/admin/interviews",
        )

    # 1. Les membres de l'entretien : ce sont eux qui le mènent.
    for membre in inv.membres:
        await _notify_rh(membre)

    # 2. Invitation creator (if different from recruiter)
    creator = None
    if invitation.created_by:
        res = await db.execute(_select(User).where(User.id == invitation.created_by))
        creator = res.scalar_one_or_none()
        if creator:
            await _notify_rh(creator)

    await db.commit()

    # Espace Meet : créé maintenant que le créneau est connu. Avant la
    # confirmation, on aurait produit une salle pour un entretien qui pouvait
    # ne jamais avoir lieu.
    background_tasks.add_task(_creer_meet_apres_confirmation, invitation.id)

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
        timezone=settings.APP_TIMEZONE,
    )


# ════════════════════════════════════════════════════════════════════
#  RH ENDPOINTS — authenticated, RH staff/manager/admin only
# ════════════════════════════════════════════════════════════════════

@router.get(
    "/membres-possibles",
    response_model=list[InterviewMemberResponse],
    dependencies=[Depends(require("interviews", "write"))],
)
async def list_membres_possibles(db: Annotated[AsyncSession, Depends(get_db)]):
    """Qui peut être choisi comme membre d'un entretien (nom et e-mail seulement)."""
    return [
        InterviewMemberResponse(id=u.id, name=u.full_name or u.username or u.email, email=u.email)
        for u in await interview_service.membres_possibles(db)
    ]


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
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: str | None = Query(None, alias="status",
                                       description="PENDING / CONFIRMED / EXPIRED / CANCELLED"),
    application_id: UUID | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
):
    # Un recruteur ne voit que les entretiens dont il est membre.
    recruiter_filter: UUID | None = current_user.id if _restreint_aux_membres(current_user) else None

    items = await interview_service.list_invitations(
        db,
        status_filter=status_filter,
        application_id=application_id,
        recruiter_id=recruiter_filter,
        limit=limit,
    )
    return [
        _reponse(
            item["invitation"], user=current_user,
            candidate_name=item["candidate_name"], candidate_email=item["candidate_email"],
            job_title=item["job_title"], job_offer_id=item["job_offer_id"],
            application_status=item["application_status"], interview_score=item["interview_score"],
        )
        for item in items
    ]


@router.get(
    "/invitations/{invitation_id}",
    response_model=InvitationResponse,
    dependencies=[Depends(require("interviews", "read"))],
)
async def get_invitation(
    invitation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return await _reponse_contexte(db, invitation_id, current_user)


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
    cible, *_ = await interview_service.get_invitation_context(db, invitation_id)
    _exiger_visibilite(cible, current_user)
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

    return await _reponse_contexte(db, inv.id, current_user)


@router.get(
    "/calendar",
    response_model=CalendarResponse,
    dependencies=[Depends(require("interviews", "read"))],
)
async def get_calendar(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    state: str | None = Query(None, description="AVAILABLE / PROPOSED / RESERVED"),
):
    items_raw = await interview_service.build_calendar(
        db, date_from=date_from, date_to=date_to, state_filter=state,
        member_id=current_user.id if _restreint_aux_membres(current_user) else None,
    )
    items = [CalendarSlot(**item) for item in items_raw]
    return CalendarResponse(total=len(items), items=items)


# ════════════════════════════════════════════════════════════════════
#  GOOGLE CALENDAR & ICS — RH only
# ════════════════════════════════════════════════════════════════════

@router.get("/google-meet/authorize")
async def google_meet_authorize(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Renvoie l'URL de consentement Google à ouvrir pour lier un compte Meet.

    L'identifiant de l'utilisateur voyage dans `state` : c'est lui qui permet,
    au retour, de savoir à qui rattacher le jeton — le retour de Google est
    une redirection de navigateur, sans en-tête d'authentification.
    """
    from app.integrations.google_meet import google_meet_client

    url = google_meet_client.url_autorisation(state=str(current_user.id))
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth non configuré (GOOGLE_CLIENT_ID / SECRET).",
        )
    return {"authorize_url": url}


@router.get("/google-meet/callback")
async def google_meet_callback(
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """
    Retour de Google après consentement. Échange le code contre un jeton de
    rafraîchissement et le rattache à l'utilisateur porté par `state`.

    Route PUBLIQUE par nécessité : Google redirige un navigateur, sans jeton
    d'authentification PIQBIT. La sécurité repose sur le code, à usage unique
    et lié au client OAuth déclaré.

    Répond par une redirection vers l'interface plutôt que par du JSON :
    l'utilisateur arrive ici dans son navigateur, pas via un appel programmé.
    """
    from fastapi.responses import RedirectResponse
    from sqlalchemy import update as _update

    from app.integrations.google_meet import google_meet_client

    base = settings.GOOGLE_MEET_POST_AUTH_REDIRECT.rstrip("/")

    if error or not code or not state:
        return RedirectResponse(f"{base}?google_meet=error")

    jeton = await asyncio.to_thread(google_meet_client.echanger_code, code)
    if not jeton:
        return RedirectResponse(f"{base}?google_meet=no_refresh_token")

    try:
        await db.execute(
            _update(User).where(User.id == UUID(state))
            .values(google_meet_refresh_token=jeton)
        )
        await db.commit()
    except Exception as exc:  # pragma: no cover - état inattendu
        logger.warning("Rattachement du jeton Meet échoué : %s", exc)
        await db.rollback()
        return RedirectResponse(f"{base}?google_meet=error")

    logger.info("Compte Google Meet lié pour l'utilisateur %s", state)
    return RedirectResponse(f"{base}?google_meet=connected")


@router.post(
    "/meet-link",
    dependencies=[Depends(require("interviews", "write"))],
)
async def generate_meet_link(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    Produit un lien de visioconférence utilisable immédiatement, AVANT que
    l'invitation n'existe.

    Appelé par le bouton « Générer un lien » du panneau de planification. Le
    lien est rendu au client, qui le renvoie avec les créneaux ; il est alors
    figé sur l'invitation.

    DEUX CHEMINS, dans cet ordre.

    1. **Google Meet**, si l'appelant a lié son compte Google. L'API Meet crée
       un espace sans événement Calendar, donc sans date — ce qui la rend
       utilisable ici, là où l'agenda ne l'était pas. L'espace appartient au
       recruteur qui a autorisé : c'est lui l'organisateur.

    2. **Salle de repli**, sinon. Ouvrable sans compte, immédiatement.

    `provider` dit lequel a servi. L'interface l'affiche tel quel : annoncer
    « Google Meet » puis livrer autre chose ferait douter du reste.
    """
    from app.integrations.google_meet import google_meet_client

    if not current_user.google_meet_refresh_token:
        # Pas de repli : on refuse en disant quoi faire. Rendre une salle de
        # secours donnerait l'illusion que tout va bien, et le problème ne
        # serait découvert qu'au moment de l'entretien.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aucun compte Google lié. Cliquez sur « Connecter Google "
                   "Meet » pour autoriser PIQBIT à créer vos réunions.",
            headers={"X-Google-Meet-Linked": "false"},
        )

    # httpx synchrone → fil, pour ne pas geler la boucle d'événements.
    resultat = await asyncio.to_thread(
        google_meet_client.creer_espace, current_user.google_meet_refresh_token,
    )
    if not resultat.get("meet_url"):
        # La raison vient de Google : elle distingue une API non activée d'une
        # autorisation révoquée, et c'est elle qui permet de corriger.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=resultat.get("error") or "Création de la réunion refusée par Google.",
        )
    return {**resultat, "google_meet_linked": True}


@router.post(
    "/invitations/{invitation_id}/meet-link",
    dependencies=[Depends(require("interviews", "write"))],
)
async def create_meet_link_for_invitation(
    invitation_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    regenerate: bool = False,
):
    """
    Crée le lien de visioconférence d'un entretien **confirmé**, et l'envoie.

    Rattrapage du chemin automatique : normalement le lien est créé dès la
    confirmation. Ce bouton sert quand cela n'a pas pu se faire — compte
    Google lié après coup, API indisponible ce jour-là — ou quand il faut
    remplacer un lien diffusé par erreur (`regenerate=true`).

    Réservé aux entretiens confirmés : sans créneau retenu, on ne sait ni à
    qui ni pour quand annoncer la réunion.

    Le compte employé est celui du recruteur assigné s'il est lié, sinon celui
    de l'appelant. L'espace appartient à son propriétaire — c'est lui
    l'organisateur de la réunion.
    """
    from app.integrations.google_meet import google_meet_client
    from app.services.email_service import send_interview_meet_link

    inv, app, candidate, user, job = await interview_service.get_invitation_context(
        db, invitation_id
    )
    if _status_str(inv) != "CONFIRMED" or not inv.confirmed_slot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seul un entretien confirmé peut recevoir un lien : "
                   "sans créneau retenu, la réunion n'a pas de date.",
        )
    if inv.meet_url and not regenerate:
        return {"meet_url": inv.meet_url, "provider": "existing", "sent": False}

    porteur = await _porteur_du_compte_meet(db, inv) or (
        current_user if current_user.google_meet_refresh_token else None
    )

    if not porteur:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aucun compte Google lié — ni pour le recruteur assigné, ni "
                   "pour vous. Connectez Google Meet depuis le panneau de "
                   "planification, puis réessayez.",
        )

    resultat = await asyncio.to_thread(
        google_meet_client.creer_espace, porteur.google_meet_refresh_token,
    )
    if not resultat.get("meet_url"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=resultat.get("error") or "Création de la réunion refusée par Google.",
        )

    inv.meet_url = resultat["meet_url"]
    await db.commit()

    # Envoi immédiat au candidat et au recruteur assigné. Le rappel de T-30
    # partira de toute façon ; celui-ci permet de préparer la réunion.
    destinataires = await interview_service.resolve_interview_recipients(db, invitation_id)
    slot = inv.confirmed_slot
    vus: set[str] = set()
    for role, email in destinataires:
        if not email or email in vus or role == "superadmin":
            continue
        vus.add(email)
        background_tasks.add_task(
            send_interview_meet_link,
            to_email=email,
            recipient_role=role,
            candidate_name=candidate.full_name,
            job_title=job.title,
            slot_start=slot.start_at,
            meet_url=inv.meet_url,
            minutes_before=0,
        )

    logger.info("Lien visio créé pour l'invitation %s, envoyé à %d destinataire(s)",
                invitation_id, len(vus))
    return {**resultat, "sent": True, "recipients": len(vus)}


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
