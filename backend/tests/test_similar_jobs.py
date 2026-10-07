"""
GET /recruitment/jobs/{job_id}/similar — section « Offres similaires » de la
page de détail.

Le classement combine compétences communes (poids fort), proximité
d'expérience requise (± 2 ans) et mode de travail identique — dans cet ordre
de priorité, comme demandé pour la fonctionnalité. Ces tests verrouillent le
classement lui-même (pas seulement que l'endpoint répond), plus les deux
garde-fous de visibilité : brouillons exclus, offre inconnue → liste vide
plutôt qu'une 404 qui casserait la page pour un aperçu RH.
"""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.core.security import hash_password
from tests.conftest import VALID_PASSWORD


async def _make_admin_token(client: AsyncClient, db: AsyncSession) -> str:
    admin = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        username=f"admin_{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password(VALID_PASSWORD),
        full_name="Admin Similar",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(admin)
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": VALID_PASSWORD},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_job(client: AsyncClient, token: str, **overrides) -> dict:
    payload = {
        "title": "Poste de test",
        "description": "Description de test suffisamment longue.",
        "required_skills": [],
        "required_experience_years": None,
        "work_mode": None,
        "status": "PUBLISHED",
    }
    payload.update(overrides)
    resp = await client.post(
        "/api/v1/recruitment/jobs", headers=_auth(token), json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_similar_jobs_ranks_by_skills_then_experience_then_mode(
    client: AsyncClient, db: AsyncSession,
):
    token = await _make_admin_token(client, db)

    reference = await _create_job(
        client, token,
        title="AI Engineer",
        required_skills=["Python", "FastAPI", "Docker"],
        required_experience_years=3,
        work_mode="REMOTE",
    )
    best_match = await _create_job(
        client, token,
        title="Backend Engineer",
        required_skills=["Python", "FastAPI", "Kubernetes"],  # 2 compétences communes
        required_experience_years=3,                            # même expérience
        work_mode="REMOTE",                                     # même mode
    )
    partial_match = await _create_job(
        client, token,
        title="Data Engineer",
        required_skills=["Python"],                             # 1 compétence commune
        required_experience_years=4,                            # proche (±2)
        work_mode="HYBRID",                                      # mode différent
    )
    no_match = await _create_job(
        client, token,
        title="Java Architect",
        required_skills=["Java", "Spring"],                      # rien en commun
        required_experience_years=10,                            # loin
        work_mode="ON_SITE",
    )

    resp = await client.get(f"/api/v1/recruitment/jobs/{reference['id']}/similar")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]

    assert reference["id"] not in ids
    assert ids.index(best_match["id"]) < ids.index(partial_match["id"]) < ids.index(no_match["id"])


@pytest.mark.asyncio
async def test_similar_jobs_excludes_drafts(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)

    reference = await _create_job(
        client, token, title="Reference", required_skills=["Python"],
    )
    draft = await _create_job(
        client, token, title="Brouillon caché",
        required_skills=["Python"], status="DRAFT",
    )

    resp = await client.get(f"/api/v1/recruitment/jobs/{reference['id']}/similar")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]
    assert draft["id"] not in ids


@pytest.mark.asyncio
async def test_similar_jobs_respects_limit(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    reference = await _create_job(client, token, title="Reference")
    for i in range(6):
        await _create_job(client, token, title=f"Autre offre {i}")

    resp = await client.get(
        f"/api/v1/recruitment/jobs/{reference['id']}/similar", params={"limit": 3},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_similar_jobs_unknown_job_returns_empty_list(client: AsyncClient):
    resp = await client.get(f"/api/v1/recruitment/jobs/{uuid.uuid4()}/similar")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_similar_jobs_is_public(client: AsyncClient, db: AsyncSession):
    """Aucune authentification requise : c'est une route candidat/anonyme."""
    token = await _make_admin_token(client, db)
    reference = await _create_job(client, token, title="Reference")

    resp = await client.get(f"/api/v1/recruitment/jobs/{reference['id']}/similar")
    assert resp.status_code == 200
