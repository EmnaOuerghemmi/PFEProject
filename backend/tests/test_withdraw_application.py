"""
POST /recruitment/my-applications/{id}/withdraw — le candidat retire sa
propre candidature.

Trois garanties couvertes :

* **Propriété.** Seul le candidat qui a déposé la candidature peut la
  retirer — un autre candidat authentifié reçoit un 404, comme partout
  ailleurs sur ce module (« introuvable » et « pas la vôtre » se confondent).
* **Non destructif.** Le dossier passe en `WITHDRAWN`, il n'est pas supprimé
  — `GET /my-applications` doit encore le lister.
* **Fin de parcours.** Une fois retirée (ou déjà recrutée/rejetée), la
  candidature ne peut plus changer d'état via cette route : 409, pas un
  second retrait silencieux.
"""
import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.recruitment import JobOffer
from app.models.user import User
from tests.conftest import VALID_PASSWORD
# Ces tests portent sur le retrait, pas sur la détection de CV (qui a ses
# propres tests) : même neutralisation du détecteur que pour le stockage.
from tests.test_candidate_cv_and_expectation import _sans_detecteur_de_cv  # noqa: F401

PDF_MINIMAL = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _fichier(nom: str = "cv.pdf") -> dict:
    return {"cv_file": (nom, io.BytesIO(PDF_MINIMAL), "application/pdf")}


async def _candidat(client: AsyncClient, db: AsyncSession) -> tuple[User, str]:
    suffixe = uuid.uuid4().hex[:8]
    email = f"cand_{suffixe}@example.com"
    user = User(
        id=uuid.uuid4(), email=email, username=f"cand_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Retrait",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    resp = await client.post("/api/v1/auth/login",
                              json={"email": email, "password": VALID_PASSWORD})
    return user, resp.json()["access_token"]


async def _offre(db: AsyncSession) -> JobOffer:
    job = JobOffer(
        title="Développeur Full Stack", description="Poste ouvert aux tests.",
        required_skills=["Python"], is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _postuler(client: AsyncClient, token: str, job_id) -> dict:
    resp = await client.post(
        f"/api/v1/recruitment/apply/{job_id}", files=_fichier(), headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_retrait_change_le_statut_sans_supprimer(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    application = await _postuler(client, token, job.id)

    resp = await client.post(
        f"/api/v1/recruitment/my-applications/{application['id']}/withdraw",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "WITHDRAWN"

    # Toujours listée, pas supprimée.
    mine = await client.get("/api/v1/recruitment/my-applications", headers=_auth(token))
    assert any(a["id"] == application["id"] and a["status"] == "WITHDRAWN"
               for a in mine.json())


@pytest.mark.asyncio
async def test_retrait_impossible_deux_fois(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    application = await _postuler(client, token, job.id)

    url = f"/api/v1/recruitment/my-applications/{application['id']}/withdraw"
    first = await client.post(url, headers=_auth(token))
    assert first.status_code == 200

    second = await client.post(url, headers=_auth(token))
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_retrait_dune_candidature_dautrui_est_refuse(client: AsyncClient, db: AsyncSession):
    _, token_a = await _candidat(client, db)
    _, token_b = await _candidat(client, db)
    job = await _offre(db)
    application = await _postuler(client, token_a, job.id)

    resp = await client.post(
        f"/api/v1/recruitment/my-applications/{application['id']}/withdraw",
        headers=_auth(token_b),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retrait_sans_authentification_refuse(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/recruitment/my-applications/{uuid.uuid4()}/withdraw",
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_score_detail_expose_le_chemin_du_cv(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    application = await _postuler(client, token, job.id)

    resp = await client.get(
        f"/api/v1/recruitment/my-applications/{application['id']}/score-detail",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["cv_file_path"]
