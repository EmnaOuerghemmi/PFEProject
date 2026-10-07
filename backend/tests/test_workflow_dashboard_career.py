"""
Tests des modules workflow, dashboard et carrière.

- **workflow** : orchestre les transitions d'une candidature (entretien,
  rejet, négociation). Une régression y bloquerait le pipeline de
  recrutement, ou pire, enverrait un e-mail de refus au mauvais candidat.
- **dashboard** : agrège les compteurs affichés en page d'accueil admin.
- **carrière** : plans d'évolution des collaborateurs.

Les envois d'e-mails partent en `BackgroundTasks` : ils ne s'exécutent pas
pendant les tests, ce qui permet de valider les transitions sans SMTP.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole

from tests.conftest import USER_PAYLOAD, VALID_PASSWORD


# ── Helpers ────────────────────────────────────────────────────────────────

def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    return resp.json()["access_token"]


async def _make_user_with_role(
    client: AsyncClient, db: AsyncSession, role: UserRole, tag: str
) -> tuple[User, str]:
    """Crée un utilisateur avec le rôle voulu et renvoie (user, jeton)."""
    email = f"{tag}_{uuid.uuid4().hex[:6]}@example.com"
    user = User(
        id=uuid.uuid4(),
        email=email,
        username=f"{tag}_{uuid.uuid4().hex[:6]}",
        hashed_password=hash_password(VALID_PASSWORD),
        full_name=f"{tag.title()} Test",
        role=role,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
    )
    return user, resp.json()["access_token"]


async def _make_application(db: AsyncSession) -> tuple[Application, JobOffer, Candidate]:
    """Crée une candidature complète (utilisateur, candidat, offre)."""
    suffixe = uuid.uuid4().hex[:8]
    user = User(
        email=f"cand_{suffixe}@example.com",
        username=f"cand_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD),
        full_name="Candidat Workflow",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()

    candidate = Candidate(user_id=user.id, full_name="Candidat Workflow")
    db.add(candidate)

    job = JobOffer(
        title="Ingénieur Test",
        description="Poste utilisé par les tests de workflow",
        required_skills=["Python"],
        required_experience_years=2,
        is_active=True,
    )
    db.add(job)
    await db.flush()

    application = Application(
        candidate_id=candidate.id,
        job_offer_id=job.id,
        cv_file_path="/tmp/cv.pdf",
        status="PENDING",
    )
    db.add(application)
    await db.commit()
    return application, job, candidate


# ══════════════════════════════════════════════════════════════════════════
#  WORKFLOW — contrôle d'accès
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rejet_refuse_sans_authentification(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/recruitment/applications/{uuid.uuid4()}/reject", json={"message": ""}
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_rejet_interdit_a_un_candidat(client: AsyncClient, db: AsyncSession):
    """
    Un candidat ne doit jamais pouvoir rejeter une candidature — la sienne
    comme celle d'un autre.
    """
    token = await _register_and_login(client, USER_PAYLOAD)
    application, _, _ = await _make_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/reject",
        json={"message": ""},
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_planification_entretien_interdite_a_un_candidat(
    client: AsyncClient, db: AsyncSession
):
    token = await _register_and_login(client, USER_PAYLOAD)
    application, _, _ = await _make_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/schedule-interview",
        json={"slots": ["2026-09-01T10:00:00"], "duration_minutes": 30},
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_negociation_interdite_au_personnel_rh_simple(
    client: AsyncClient, db: AsyncSession
):
    """
    La négociation salariale engage l'entreprise financièrement : elle est
    réservée aux ADMIN et RH_MANAGER, contrairement au rejet ou à la
    planification d'entretien, ouverts au RH_STAFF.
    """
    _, token = await _make_user_with_role(client, db, UserRole.RECRUTEUR, "staff")
    application, _, _ = await _make_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/start-negotiation",
        json={"employer_offer": 3000},
        headers=_auth(token),
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
#  WORKFLOW — transitions de statut
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rejet_bascule_le_statut_en_rejected(
    client: AsyncClient, db: AsyncSession
):
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    application, _, _ = await _make_application(db)
    assert application.status == "PENDING"

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/reject",
        json={"message": "Profil non retenu."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["email_sent"] is True

    rafraichie = await db.get(Application, application.id)
    await db.refresh(rafraichie)
    assert rafraichie.status == "REJECTED"


@pytest.mark.asyncio
async def test_planification_entretien_bascule_le_statut(
    client: AsyncClient, db: AsyncSession
):
    _, token = await _make_user_with_role(client, db, UserRole.RH, "rh")
    application, _, _ = await _make_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/schedule-interview",
        json={
            "slots": ["2026-09-01T10:00:00", "2026-09-02T14:00:00"],
            "duration_minutes": 45,
            "message": "Merci de choisir un créneau.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200

    rafraichie = await db.get(Application, application.id)
    await db.refresh(rafraichie)
    assert rafraichie.status == "INTERVIEW_SCHEDULED"


@pytest.mark.asyncio
@pytest.mark.parametrize("statut", ["REJECTED", "WITHDRAWN", "HIRED", "ACCEPTED"])
async def test_planification_refusee_quand_le_dossier_ne_peut_pas_reculer(
    client: AsyncClient, db: AsyncSession, statut: str
):
    """
    Planifier remet la candidature en « entretien planifié ». Pour un dossier
    clos ou déjà accepté, ce serait un retour en arrière que `can_transition`
    interdit partout ailleurs : l'endpoint ne doit pas le permettre, et surtout
    ne pas envoyer d'invitation à un candidat écarté.
    """
    _, token = await _make_user_with_role(client, db, UserRole.RH, "rh")
    application, _, _ = await _make_application(db)
    application.status = statut
    await db.commit()

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/schedule-interview",
        json={"slots": ["2026-09-01T10:00:00"]},
        headers=_auth(token),
    )
    assert resp.status_code == 409

    rafraichie = await db.get(Application, application.id)
    await db.refresh(rafraichie)
    assert rafraichie.status == statut


@pytest.mark.asyncio
@pytest.mark.parametrize("statut", ["INTERVIEW_SCHEDULED", "NEGOTIATION", "TEST_DONE"])
async def test_replanifier_ou_rouvrir_un_entretien_reste_permis(
    client: AsyncClient, db: AsyncSession, statut: str
):
    """Un second entretien est courant, et une négociation qui bute y ramène."""
    _, token = await _make_user_with_role(client, db, UserRole.RECRUTEUR, "rec")
    application, _, _ = await _make_application(db)
    application.status = statut
    await db.commit()

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/schedule-interview",
        json={"slots": ["2026-09-01T10:00:00"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_planification_exige_au_moins_un_creneau(
    client: AsyncClient, db: AsyncSession
):
    """Une invitation sans créneau laisserait le candidat sans action possible."""
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    application, _, _ = await _make_application(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{application.id}/schedule-interview",
        json={"slots": []},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_workflow_candidature_inexistante_renvoie_404(
    client: AsyncClient, db: AsyncSession
):
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    resp = await client.post(
        f"/api/v1/recruitment/applications/{uuid.uuid4()}/reject",
        json={"message": ""},
        headers=_auth(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rejet_notifie_le_candidat(client: AsyncClient, db: AsyncSession):
    """Le candidat doit être informé dans l'application, pas seulement par e-mail."""
    from app.models.notification import Notification

    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    application, _, candidate = await _make_application(db)

    await client.post(
        f"/api/v1/recruitment/applications/{application.id}/reject",
        json={"message": ""},
        headers=_auth(token),
    )

    notifications = (
        await db.execute(
            select(Notification).where(Notification.recipient_id == candidate.user_id)
        )
    ).scalars().all()
    assert len(notifications) >= 1
    assert any("rejet" in (n.title or "").lower() for n in notifications)


# ══════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_dashboard_exige_une_authentification(client: AsyncClient):
    for route in ("stats", "recent-applications", "open-positions"):
        resp = await client.get(f"/api/v1/dashboard/{route}")
        assert resp.status_code in (401, 403), f"/dashboard/{route} accessible sans jeton"


@pytest.mark.asyncio
async def test_dashboard_stats_compte_offres_et_candidatures(
    client: AsyncClient, db: AsyncSession
):
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    await _make_application(db)  # 1 offre active + 1 candidature

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.status_code == 200

    data = resp.json()
    assert data["total_jobs"] == 1
    assert data["total_applications"] == 1
    # Aucune candidature acceptée pour l'instant.
    assert data["total_hires"] == 0


@pytest.mark.asyncio
async def test_dashboard_compte_les_embauches(client: AsyncClient, db: AsyncSession):
    """ACCEPTED et HIRED comptent tous deux comme des embauches."""
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    application, _, _ = await _make_application(db)
    application.status = "ACCEPTED"
    await db.commit()

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.json()["total_hires"] == 1


@pytest.mark.asyncio
async def test_dashboard_ignore_les_offres_fermees(
    client: AsyncClient, db: AsyncSession
):
    """`total_jobs` ne doit compter que les postes encore ouverts."""
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")
    _, job, _ = await _make_application(db)
    job.is_active = False
    await db.commit()

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.json()["total_jobs"] == 0


@pytest.mark.asyncio
async def test_dashboard_sur_base_vide(client: AsyncClient, db: AsyncSession):
    """Aucune donnée ne doit pas produire d'erreur mais des compteurs à zéro."""
    _, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_jobs"] == 0
    assert data["total_applications"] == 0

    for route in ("recent-applications", "open-positions"):
        r = await client.get(f"/api/v1/dashboard/{route}", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ══════════════════════════════════════════════════════════════════════════
#  CARRIÈRE
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_career_plans_exige_une_authentification(client: AsyncClient):
    resp = await client.get("/api/v1/career/plans")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_career_creation_et_lecture_d_un_plan(
    client: AsyncClient, db: AsyncSession
):
    admin, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")

    creation = await client.post(
        "/api/v1/career/plans",
        json={
            "user_id": str(admin.id),
            "current_position": "Développeur",
            "target_position": "Tech Lead",
            "status": "IN_PROGRESS",
            "progress": 25.0,
        },
        headers=_auth(token),
    )
    assert creation.status_code == 201
    plan = creation.json()
    assert plan["target_position"] == "Tech Lead"
    assert plan["progress"] == 25.0

    liste = await client.get("/api/v1/career/plans", headers=_auth(token))
    assert liste.status_code == 200
    assert any(p["id"] == plan["id"] for p in liste.json())


@pytest.mark.asyncio
async def test_career_statut_invalide_refuse(client: AsyncClient, db: AsyncSession):
    """Le statut est contraint par une expression régulière côté schéma."""
    admin, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")

    resp = await client.post(
        "/api/v1/career/plans",
        json={"user_id": str(admin.id), "status": "STATUT_INVENTE"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_career_progression_hors_bornes_refusee(
    client: AsyncClient, db: AsyncSession
):
    """La progression est un pourcentage : 0 à 100."""
    admin, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")

    resp = await client.post(
        "/api/v1/career/plans",
        json={"user_id": str(admin.id), "progress": 150},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_career_mise_a_jour_et_suppression(
    client: AsyncClient, db: AsyncSession
):
    admin, token = await _make_user_with_role(client, db, UserRole.ADMIN, "adm")

    plan_id = (
        await client.post(
            "/api/v1/career/plans",
            json={"user_id": str(admin.id), "target_position": "Architecte"},
            headers=_auth(token),
        )
    ).json()["id"]

    maj = await client.patch(
        f"/api/v1/career/plans/{plan_id}",
        json={"progress": 80.0, "status": "PROMOTION_PLANNED"},
        headers=_auth(token),
    )
    assert maj.status_code == 200
    assert maj.json()["progress"] == 80.0
    assert maj.json()["status"] == "PROMOTION_PLANNED"

    suppression = await client.delete(
        f"/api/v1/career/plans/{plan_id}", headers=_auth(token)
    )
    assert suppression.status_code == 204

    restants = (await client.get("/api/v1/career/plans", headers=_auth(token))).json()
    assert all(p["id"] != plan_id for p in restants)
