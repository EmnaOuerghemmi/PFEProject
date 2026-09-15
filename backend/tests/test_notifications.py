"""
Tests du système de notifications (V1.5) :
  - service : create / notify_user / notify_admins (no-op si acteur = ADMIN) /
    list paginée / unread-count / mark_read / mark_all_read / delete
  - API : RBAC (401), CRUD bout-en-bout
  - triggers métier : changement de statut de candidature notifie le
    candidat ET les admins (si l'acteur est RH), entretien planifié idem,
    action RH (création offre) notifie les admins mais pas si l'acteur
    est déjà admin (pas d'auto-notification)
"""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Candidate, Application
from app.services.notification_service import notification_service
from tests.conftest import VALID_PASSWORD, USER_PAYLOAD


async def _make_user(db: AsyncSession, *, email: str, role: str, username: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(), email=email, username=username or email.split("@")[0],
        hashed_password=hash_password(VALID_PASSWORD), full_name=email.split("@")[0].title(),
        role=role, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _login(client: AsyncClient, email: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Service ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_user_creates_row(db: AsyncSession):
    recipient = await _make_user(db, email="cand_notif@example.com", role=UserRole.CANDIDAT)
    await db.commit()

    notif = await notification_service.notify_user(
        db, recipient_id=recipient.id, type="TEST", title="Titre", message="Msg", link="/x",
    )
    assert notif.id is not None
    assert notif.is_read is False

    listing = await notification_service.list_for_user(db, user_id=recipient.id)
    assert listing["total"] == 1
    assert listing["items"][0]["title"] == "Titre"


@pytest.mark.asyncio
async def test_notify_admins_reaches_all_admins_not_self(db: AsyncSession):
    admin1 = await _make_user(db, email="admin1@example.com", role=UserRole.ADMIN)
    admin2 = await _make_user(db, email="admin2@example.com", role=UserRole.ADMIN)
    rh = await _make_user(db, email="rh_actor@example.com", role=UserRole.RH)
    await db.commit()

    created = await notification_service.notify_admins(
        db, actor=rh, type="JOB_CREATED", title="T", message="M",
    )
    await db.commit()
    assert len(created) == 2
    recipients = {n.recipient_id for n in created}
    assert recipients == {admin1.id, admin2.id}


@pytest.mark.asyncio
async def test_notify_admins_noop_when_actor_is_admin(db: AsyncSession):
    admin1 = await _make_user(db, email="admin_a@example.com", role=UserRole.ADMIN)
    admin_actor = await _make_user(db, email="admin_actor@example.com", role=UserRole.ADMIN)
    await db.commit()

    created = await notification_service.notify_admins(
        db, actor=admin_actor, type="JOB_CREATED", title="T", message="M",
    )
    assert created == []


@pytest.mark.asyncio
async def test_mark_read_and_unread_count(db: AsyncSession):
    user = await _make_user(db, email="mr_user@example.com", role=UserRole.CANDIDAT)
    await db.commit()
    n1 = await notification_service.notify_user(db, recipient_id=user.id, type="A", title="a", message="a")
    await notification_service.notify_user(db, recipient_id=user.id, type="B", title="b", message="b")
    await db.commit()

    assert await notification_service.unread_count(db, user.id) == 2

    marked = await notification_service.mark_read(db, notification_id=n1.id, user_id=user.id)
    assert marked.is_read is True
    await db.commit()
    assert await notification_service.unread_count(db, user.id) == 1

    count = await notification_service.mark_all_read(db, user.id)
    await db.commit()
    assert count == 1
    assert await notification_service.unread_count(db, user.id) == 0


@pytest.mark.asyncio
async def test_delete_notification(db: AsyncSession):
    user = await _make_user(db, email="del_user@example.com", role=UserRole.CANDIDAT)
    await db.commit()
    n = await notification_service.notify_user(db, recipient_id=user.id, type="A", title="a", message="a")
    await db.commit()

    deleted = await notification_service.delete(db, notification_id=n.id, user_id=user.id)
    assert deleted is True
    listing = await notification_service.list_for_user(db, user_id=user.id)
    assert listing["total"] == 0

    # Suppression d'une notif inexistante / d'un autre user → False.
    assert await notification_service.delete(db, notification_id=uuid.uuid4(), user_id=user.id) is False


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notifications_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_notifications_api_crud_flow(client: AsyncClient, db: AsyncSession):
    user = await _make_user(db, email="api_user@example.com", role=UserRole.CANDIDAT)
    await db.commit()
    token = await _login(client, "api_user@example.com")

    await notification_service.notify_user(db, recipient_id=user.id, type="A", title="Un", message="msg1")
    await notification_service.notify_user(db, recipient_id=user.id, type="B", title="Deux", message="msg2")
    await db.commit()

    listing = await client.get("/api/v1/notifications", headers=_auth(token))
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 2
    assert set(data) >= {"items", "total", "page", "pages", "page_size"}

    unread = await client.get("/api/v1/notifications/unread-count", headers=_auth(token))
    assert unread.json()["unread_count"] == 2

    notif_id = data["items"][0]["id"]
    marked = await client.patch(f"/api/v1/notifications/{notif_id}/read", headers=_auth(token))
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    unread2 = await client.get("/api/v1/notifications/unread-count", headers=_auth(token))
    assert unread2.json()["unread_count"] == 1

    read_all = await client.post("/api/v1/notifications/read-all", headers=_auth(token))
    assert read_all.json()["marked_read"] == 1

    dele = await client.delete(f"/api/v1/notifications/{notif_id}", headers=_auth(token))
    assert dele.status_code == 204
    dele_again = await client.delete(f"/api/v1/notifications/{notif_id}", headers=_auth(token))
    assert dele_again.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_read_others_notifications(client: AsyncClient, db: AsyncSession):
    owner = await _make_user(db, email="owner@example.com", role=UserRole.CANDIDAT)
    intruder = await _make_user(db, email="intruder@example.com", role=UserRole.CANDIDAT)
    await db.commit()
    n = await notification_service.notify_user(db, recipient_id=owner.id, type="A", title="a", message="a")
    await db.commit()

    intruder_token = await _login(client, "intruder@example.com")
    resp = await client.patch(f"/api/v1/notifications/{n.id}/read", headers=_auth(intruder_token))
    assert resp.status_code == 404  # scoping par recipient_id → invisible pour un autre user


# ── Triggers métier ────────────────────────────────────────────────────────────

async def _make_admin_token(client: AsyncClient, db: AsyncSession, email="admin_trig@example.com") -> tuple[User, str]:
    admin = await _make_user(db, email=email, role=UserRole.ADMIN)
    await db.commit()
    token = await _login(client, email)
    return admin, token


async def _make_rh_token(client: AsyncClient, db: AsyncSession, email="rh_trig@example.com") -> tuple[User, str]:
    rh = await _make_user(db, email=email, role=UserRole.RH)
    await db.commit()
    token = await _login(client, email)
    return rh, token


@pytest.mark.asyncio
async def test_job_created_by_rh_notifies_admin(client: AsyncClient, db: AsyncSession):
    admin, _ = await _make_admin_token(client, db)
    rh, rh_token = await _make_rh_token(client, db)

    resp = await client.post(
        "/api/v1/recruitment/jobs",
        json={"title": "Backend Developer", "description": "description de test suffisamment longue"},
        headers=_auth(rh_token),
    )
    assert resp.status_code == 201, resp.text

    listing = await notification_service.list_for_user(db, user_id=admin.id)
    assert listing["total"] == 1
    assert listing["items"][0]["type"] == "JOB_CREATED"
    assert "Backend Developer" in listing["items"][0]["message"]


@pytest.mark.asyncio
async def test_job_created_by_admin_does_not_self_notify(client: AsyncClient, db: AsyncSession):
    admin, admin_token = await _make_admin_token(client, db, email="solo_admin@example.com")

    resp = await client.post(
        "/api/v1/recruitment/jobs",
        json={"title": "Solo Admin Job", "description": "description de test suffisamment longue"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201

    listing = await notification_service.list_for_user(db, user_id=admin.id)
    assert listing["total"] == 0


@pytest.mark.asyncio
async def test_application_status_change_notifies_candidate_and_admin(client: AsyncClient, db: AsyncSession):
    admin, _ = await _make_admin_token(client, db, email="admin_appstatus@example.com")
    rh, rh_token = await _make_rh_token(client, db, email="rh_appstatus@example.com")

    candidate_user = await _make_user(db, email="candidate_appstatus@example.com", role=UserRole.CANDIDAT)
    candidate = Candidate(id=uuid.uuid4(), user_id=candidate_user.id, full_name="Candidat Test")
    job = JobOffer(id=uuid.uuid4(), title="QA Engineer", description="x", created_by=rh.id)
    db.add_all([candidate, job])
    await db.flush()
    application = Application(
        id=uuid.uuid4(), candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path="cv.pdf", status="PENDING",
    )
    db.add(application)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/recruitment/applications/{application.id}",
        json={"status": "ACCEPTED"},
        headers=_auth(rh_token),
    )
    assert resp.status_code == 200, resp.text

    cand_notifs = await notification_service.list_for_user(db, user_id=candidate_user.id)
    assert cand_notifs["total"] == 1
    assert cand_notifs["items"][0]["type"] == "APPLICATION_STATUS_CHANGED"
    assert "Acceptée" in cand_notifs["items"][0]["message"]

    admin_notifs = await notification_service.list_for_user(db, user_id=admin.id)
    assert admin_notifs["total"] == 1
    assert admin_notifs["items"][0]["type"] == "APPLICATION_STATUS_CHANGED"
