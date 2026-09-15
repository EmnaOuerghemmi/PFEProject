"""
Tests du volet calendrier de la gestion d'entretiens (V1.4) :
  - GET /interview/google-status : dégradation gracieuse sans credentials
  - POST /interview/invitations/{id}/sync-google : 503 quand non configuré
  - GET /interview/invitations/{id}/ics : ICS valide pour un entretien confirmé,
    409 pour un entretien non confirmé
  - build_ics : contenu RFC 5545
  - colonne google_event_id présente sur le modèle
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Candidate, Application
from app.models.interview import InterviewInvitation, InterviewSlot, InvitationStatus
from tests.conftest import VALID_PASSWORD


async def _make_admin_token(client: AsyncClient, db: AsyncSession) -> str:
    admin = User(
        id=uuid.uuid4(),
        email="admin_cal@example.com",
        username="admin_cal",
        hashed_password=hash_password(VALID_PASSWORD),
        full_name="Admin Cal",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_cal@example.com", "password": VALID_PASSWORD},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_confirmed_invitation(db: AsyncSession) -> InterviewInvitation:
    """Crée user+candidat+offre+candidature+invitation CONFIRMÉE avec un slot choisi."""
    user = User(
        id=uuid.uuid4(), email="cand_cal@example.com", username="cand_cal",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Cal",
        role=UserRole.CANDIDAT, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidate = Candidate(id=uuid.uuid4(), user_id=user.id, full_name="Candidat Cal")
    job = JobOffer(id=uuid.uuid4(), title="Backend Developer", description="x")
    db.add_all([candidate, job])
    await db.flush()
    application = Application(
        id=uuid.uuid4(), candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path="cv.pdf", status="INTERVIEW_SCHEDULED",
    )
    db.add(application)
    await db.flush()

    start = datetime.now(timezone.utc) + timedelta(days=2)
    invitation = InterviewInvitation(
        id=uuid.uuid4(), application_id=application.id,
        token=uuid.uuid4().hex, status=InvitationStatus.CONFIRMED,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(invitation)
    await db.flush()
    slot = InterviewSlot(
        id=uuid.uuid4(), invitation_id=invitation.id,
        start_at=start, end_at=start + timedelta(minutes=45), is_selected=True,
    )
    db.add(slot)
    await db.flush()
    invitation.confirmed_slot_id = slot.id
    await db.commit()
    return invitation


# ── Modèle / ICS pur ──────────────────────────────────────────────────────────

def test_model_has_google_event_id():
    assert hasattr(InterviewInvitation, "google_event_id")


def test_build_ics_rfc5545():
    from app.services.email_service import build_ics
    start = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
    ics = build_ics(
        summary="Entretien test", description="desc",
        start_at=start, end_at=start + timedelta(minutes=30),
        attendee_email="c@x.tn",
    )
    text = ics.decode()
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert "DTSTART:20260710T090000Z" in text
    assert "SUMMARY:Entretien test" in text


# ── Google status / sync ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_google_status_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/interview/google-status")
    assert resp.status_code == 401


from app.integrations.google_calendar import google_calendar_client

_GOOGLE_CONFIGURED = google_calendar_client.available
_SKIP_REASON = "Google Calendar est configuré dans cet environnement (.env) — test de dégradation non applicable"


@pytest.mark.asyncio
@pytest.mark.skipif(_GOOGLE_CONFIGURED, reason=_SKIP_REASON)
async def test_google_status_unconfigured(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    resp = await client.get("/api/v1/interview/google-status", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    # Sans credentials en environnement de test : non configuré + raison lisible.
    assert data["configured"] is False
    assert data["reason"]


@pytest.mark.asyncio
@pytest.mark.skipif(_GOOGLE_CONFIGURED, reason=_SKIP_REASON)
async def test_sync_google_503_when_unconfigured(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    invitation = await _make_confirmed_invitation(db)
    resp = await client.post(
        f"/api/v1/interview/invitations/{invitation.id}/sync-google", headers=_auth(token)
    )
    assert resp.status_code == 503
    assert "GOOGLE_CALENDAR" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.skipif(not _GOOGLE_CONFIGURED, reason="Google Calendar non configuré dans cet environnement")
async def test_sync_google_reuses_request_session(client: AsyncClient, db: AsyncSession, monkeypatch):
    """
    Non-régression : l'endpoint de resync manuel doit réutiliser la session
    de la requête (celle qui voit l'invitation de test) plutôt que d'ouvrir
    une session séparée sur la vraie base — sinon l'invitation de test y est
    introuvable (404 interne) et l'appel échoue en 502.

    L'appel réseau réel à Google est mocké : on ne veut pas créer un vrai
    événement dans l'agenda pour un candidat de test.
    """
    monkeypatch.setattr(
        google_calendar_client, "create_interview_event", lambda **kwargs: "evt_test_123"
    )
    token = await _make_admin_token(client, db)
    invitation = await _make_confirmed_invitation(db)
    resp = await client.post(
        f"/api/v1/interview/invitations/{invitation.id}/sync-google", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["synced"] is True
    assert data["google_event_id"] == "evt_test_123"


# ── ICS endpoint ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_ics_for_confirmed_interview(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    invitation = await _make_confirmed_invitation(db)

    resp = await client.get(
        f"/api/v1/interview/invitations/{invitation.id}/ics", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.text
    assert "BEGIN:VCALENDAR" in body
    assert "Candidat Cal" in body
    assert "Backend Developer" in body


@pytest.mark.asyncio
async def test_download_ics_409_when_not_confirmed(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    invitation = await _make_confirmed_invitation(db)
    # Repasse l'invitation en PENDING sans slot confirmé.
    invitation.status = InvitationStatus.PENDING
    invitation.confirmed_slot_id = None
    await db.commit()

    resp = await client.get(
        f"/api/v1/interview/invitations/{invitation.id}/ics", headers=_auth(token)
    )
    assert resp.status_code == 409
