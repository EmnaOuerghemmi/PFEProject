"""
Tests du CV de référence du candidat et de la prétention salariale.

Deux nouveautés y sont couvertes :

* **Le CV du profil.** Facultatif à l'inscription, déposable et remplaçable
  depuis l'espace candidat. Postuler n'exige plus de rejoindre un fichier : à
  défaut, on reprend le CV enregistré.
* **La prétention salariale.** Demandée APRÈS l'envoi du dossier, donc
  facultative par construction — la candidature existe déjà quand la question
  est posée.

Le point le plus important est vérifié ici : une candidature garde sa PROPRE
copie du CV. Remplacer son CV de profil ne doit pas réécrire un dossier déjà
déposé, sinon le document analysé et scoré ne serait plus celui sur lequel le
RH a décidé.
"""
import io
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User

from tests.conftest import VALID_PASSWORD

PDF_MINIMAL = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.fixture(autouse=True)
def _sans_detecteur_de_cv(monkeypatch):
    """
    Ces tests portent sur le STOCKAGE du CV, pas sur sa détection — qui a ses
    propres tests (test_cv_detection.py). Le PDF minimal déposé ici ne contient
    aucun texte : le détecteur le refuserait, à raison, comme illisible.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "CV_DETECTOR_ENABLED", False)


def _fichier(nom: str = "cv.pdf", contenu: bytes = PDF_MINIMAL) -> dict:
    return {"cv_file": (nom, io.BytesIO(contenu), "application/pdf")}


async def _candidat(client: AsyncClient, db: AsyncSession) -> tuple[User, str]:
    suffixe = uuid.uuid4().hex[:8]
    email = f"cand_{suffixe}@example.com"
    user = User(
        id=uuid.uuid4(), email=email, username=f"cand_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat CV",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": VALID_PASSWORD})
    return user, resp.json()["access_token"]


async def _offre(db: AsyncSession, **overrides) -> JobOffer:
    job = JobOffer(
        title=overrides.get("title", "Développeur Full Stack"),
        description="Poste ouvert aux tests.",
        required_skills=["Python"], required_experience_years=2,
        salary_min=1400, salary_max=1700,
        is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── CV de référence ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_nouveau_candidat_na_pas_de_cv(client: AsyncClient, db: AsyncSession):
    """« Pas encore de CV » est un état normal, pas une erreur."""
    _, token = await _candidat(client, db)
    resp = await client.get("/api/v1/recruitment/me/cv", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["has_cv"] is False


@pytest.mark.asyncio
async def test_depot_puis_relecture_du_cv(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    resp = await client.post("/api/v1/recruitment/me/cv",
                             files=_fichier("mon-cv.pdf"), headers=_auth(token))
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["has_cv"] is True
    assert corps["filename"] == "mon-cv.pdf"
    assert corps["uploaded_at"]

    relu = (await client.get("/api/v1/recruitment/me/cv", headers=_auth(token))).json()
    assert relu["has_cv"] is True


@pytest.mark.asyncio
async def test_le_chemin_du_fichier_nest_jamais_expose(client: AsyncClient, db: AsyncSession):
    """Publier l'arborescence du serveur invite à tenter d'y accéder."""
    _, token = await _candidat(client, db)
    resp = await client.post("/api/v1/recruitment/me/cv",
                             files=_fichier(), headers=_auth(token))
    assert "cv_path" not in resp.json()
    assert "uploads" not in resp.text


@pytest.mark.asyncio
async def test_remplacer_le_cv_supprime_lancien_fichier(client: AsyncClient, db: AsyncSession):
    user, token = await _candidat(client, db)
    await client.post("/api/v1/recruitment/me/cv", files=_fichier("v1.pdf"), headers=_auth(token))
    candidat = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()
    premier = candidat.cv_path

    await client.post("/api/v1/recruitment/me/cv", files=_fichier("v2.pdf"), headers=_auth(token))
    await db.refresh(candidat)
    assert candidat.cv_path != premier, "le nouveau dépôt doit changer de chemin"
    assert candidat.cv_filename == "v2.pdf"
    assert not Path(premier).exists(), "l'ancien fichier doit être nettoyé"


@pytest.mark.asyncio
async def test_suppression_du_cv_de_profil(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    await client.post("/api/v1/recruitment/me/cv", files=_fichier(), headers=_auth(token))
    resp = await client.delete("/api/v1/recruitment/me/cv", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["has_cv"] is False


@pytest.mark.asyncio
async def test_format_refuse(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    resp = await client.post(
        "/api/v1/recruitment/me/cv",
        files={"cv_file": ("photo.png", io.BytesIO(b"\x89PNG\r\n"), "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_fichier_vide_refuse(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    resp = await client.post(
        "/api/v1/recruitment/me/cv",
        files={"cv_file": ("vide.pdf", io.BytesIO(b""), "application/pdf")},
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cv_interdit_sans_authentification(client: AsyncClient):
    assert (await client.get("/api/v1/recruitment/me/cv")).status_code in (401, 403)


# ── Candidature sans fichier joint ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_postuler_sans_fichier_utilise_le_cv_du_profil(
    client: AsyncClient, db: AsyncSession
):
    """Le cœur de la fonctionnalité : un CV déposé une fois suffit."""
    _, token = await _candidat(client, db)
    job = await _offre(db)
    await client.post("/api/v1/recruitment/me/cv", files=_fichier(), headers=_auth(token))

    resp = await client.post(f"/api/v1/recruitment/apply/{job.id}", headers=_auth(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["cv_file_path"]


@pytest.mark.asyncio
async def test_postuler_sans_cv_du_tout_est_refuse(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    resp = await client.post(f"/api/v1/recruitment/apply/{job.id}", headers=_auth(token))
    assert resp.status_code == 400
    assert "CV" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_la_candidature_garde_sa_propre_copie_du_cv(
    client: AsyncClient, db: AsyncSession
):
    """
    Régression majeure à éviter : remplacer son CV de profil ne doit pas
    réécrire un dossier déjà déposé, sinon le document analysé cesse de
    correspondre au score calculé.
    """
    user, token = await _candidat(client, db)
    job = await _offre(db)
    await client.post("/api/v1/recruitment/me/cv", files=_fichier("v1.pdf"), headers=_auth(token))
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                headers=_auth(token))).json()["id"]

    application = (await db.execute(
        select(Application).where(Application.id == uuid.UUID(app_id)))).scalar_one()
    chemin_candidature = application.cv_file_path
    candidat = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()

    assert chemin_candidature != candidat.cv_path, "la candidature doit avoir SA copie"

    # Le candidat remplace son CV : le dossier déposé ne bouge pas.
    await client.post("/api/v1/recruitment/me/cv",
                      files=_fichier("v2.pdf", b"%PDF-1.4 AUTRE CONTENU\n%%EOF"),
                      headers=_auth(token))
    assert Path(chemin_candidature).exists()
    assert Path(chemin_candidature).read_bytes() == PDF_MINIMAL


@pytest.mark.asyncio
async def test_postuler_avec_un_fichier_met_a_jour_le_profil(
    client: AsyncClient, db: AsyncSession
):
    """Mettre son CV à jour en postulant évite d'avoir à le redéposer ensuite."""
    user, token = await _candidat(client, db)
    job = await _offre(db)
    resp = await client.post(f"/api/v1/recruitment/apply/{job.id}",
                             files=_fichier("depuis-candidature.pdf"), headers=_auth(token))
    assert resp.status_code == 201, resp.text

    candidat = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()
    assert candidat.cv_path, "le CV de profil doit avoir été renseigné"
    assert candidat.cv_filename == "depuis-candidature.pdf"


@pytest.mark.asyncio
async def test_postuler_sans_enregistrer_dans_le_profil(client: AsyncClient, db: AsyncSession):
    """`save_to_profile=false` : CV ponctuel, le profil reste inchangé."""
    user, token = await _candidat(client, db)
    job = await _offre(db)
    resp = await client.post(
        f"/api/v1/recruitment/apply/{job.id}",
        files=_fichier("ponctuel.pdf"), data={"save_to_profile": "false"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    candidat = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()
    assert candidat.cv_path is None


# ── Prétention salariale ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_pretention_est_enregistree(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                files=_fichier(), headers=_auth(token))).json()["id"]

    resp = await client.patch(
        f"/api/v1/recruitment/applications/{app_id}/expected-salary",
        json={"expected_salary": 1650}, headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["expected_salary"] == 1650


@pytest.mark.asyncio
async def test_la_candidature_existe_avant_la_question(client: AsyncClient, db: AsyncSession):
    """
    La prétention étant demandée après coup, un candidat qui n'y répond pas
    conserve sa candidature — c'est tout l'intérêt de séparer les deux étapes.
    """
    _, token = await _candidat(client, db)
    job = await _offre(db)
    corps = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                               files=_fichier(), headers=_auth(token))).json()
    assert corps["expected_salary"] is None
    mes = (await client.get("/api/v1/recruitment/my-applications", headers=_auth(token))).json()
    assert len(mes) == 1


@pytest.mark.asyncio
async def test_la_pretention_peut_etre_effacee(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                files=_fichier(), headers=_auth(token))).json()["id"]
    url = f"/api/v1/recruitment/applications/{app_id}/expected-salary"
    await client.patch(url, json={"expected_salary": 1650}, headers=_auth(token))
    resp = await client.patch(url, json={"expected_salary": None}, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["expected_salary"] is None


@pytest.mark.asyncio
async def test_montant_aberrant_refuse(client: AsyncClient, db: AsyncSession):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                files=_fichier(), headers=_auth(token))).json()["id"]
    url = f"/api/v1/recruitment/applications/{app_id}/expected-salary"
    for montant in (-500, 0, 999_999):
        resp = await client.patch(url, json={"expected_salary": montant}, headers=_auth(token))
        assert resp.status_code == 422, f"{montant} aurait dû être refusé"


@pytest.mark.asyncio
async def test_un_tiers_ne_peut_pas_fixer_la_pretention(client: AsyncClient, db: AsyncSession):
    """Un montant de négociation n'est renseignable que par l'intéressé."""
    _, token = await _candidat(client, db)
    _, token_autre = await _candidat(client, db)
    job = await _offre(db)
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                files=_fichier(), headers=_auth(token))).json()["id"]

    resp = await client.patch(
        f"/api/v1/recruitment/applications/{app_id}/expected-salary",
        json={"expected_salary": 9000}, headers=_auth(token_autre),
    )
    # 404 et non 403 : un 403 confirmerait l'existence du dossier.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_la_pretention_remonte_dans_mes_candidatures(
    client: AsyncClient, db: AsyncSession
):
    _, token = await _candidat(client, db)
    job = await _offre(db)
    app_id = (await client.post(f"/api/v1/recruitment/apply/{job.id}",
                                files=_fichier(), headers=_auth(token))).json()["id"]
    await client.patch(f"/api/v1/recruitment/applications/{app_id}/expected-salary",
                       json={"expected_salary": 1500}, headers=_auth(token))

    mes = (await client.get("/api/v1/recruitment/my-applications", headers=_auth(token))).json()
    assert mes[0]["expected_salary"] == 1500
