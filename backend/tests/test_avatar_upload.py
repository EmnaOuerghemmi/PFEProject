"""
Photo de profil.

Trois garanties :

* une vraie photo de smartphone passe — la limite de 2 Mo les refusait presque
  toutes ;
* un fichier trop lourd est refusé sans être lu en entier ;
* le FORMAT est jugé sur le contenu : les photos sont servies telles quelles
  depuis /static, donc un « photo.html » déclaré comme image ne doit jamais
  y atterrir sous une extension exécutable par le navigateur.
"""
import io
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import agents
from app.core.security import hash_password
from app.models.user import User

from tests.conftest import VALID_PASSWORD

URL = "/api/v1/users/me/avatar"

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _dossier_temporaire(tmp_path, monkeypatch) -> Path:
    """Les photos des tests n'ont rien à faire dans le vrai dossier static."""
    monkeypatch.setattr(agents, "_AVATAR_DIR", str(tmp_path))
    return tmp_path


async def _connecte(client: AsyncClient, db: AsyncSession) -> tuple[User, dict]:
    suffixe = uuid.uuid4().hex[:8]
    email = f"photo_{suffixe}@example.com"
    user = User(
        id=uuid.uuid4(), email=email, username=f"photo_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Photo Test",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _image(contenu: bytes, nom: str = "photo.jpg", type_mime: str = "image/jpeg") -> dict:
    return {"file": (nom, io.BytesIO(contenu), type_mime)}


@pytest.mark.asyncio
async def test_une_photo_de_smartphone_de_trois_mo_est_acceptee(client, db):
    _, entetes = await _connecte(client, db)
    photo = JPEG + b"\x00" * (3 * 1024 * 1024)
    resp = await client.post(URL, files=_image(photo), headers=entetes)
    assert resp.status_code == 200
    assert "/static/avatars/" in resp.json()["avatar_url"]


@pytest.mark.asyncio
async def test_une_photo_au_dela_de_la_limite_est_refusee(client, db):
    _, entetes = await _connecte(client, db)
    trop = JPEG + b"\x00" * agents._MAX_SIZE
    resp = await client.post(URL, files=_image(trop), headers=entetes)
    assert resp.status_code == 413
    assert "10 Mo" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_l_extension_vient_du_contenu_pas_du_nom(client, db, _dossier_temporaire):
    """Un PNG nommé « .html » est enregistré en .png, jamais en .html."""
    user, entetes = await _connecte(client, db)
    resp = await client.post(URL, files=_image(PNG, "photo.html", "image/png"), headers=entetes)
    assert resp.status_code == 200
    assert (_dossier_temporaire / f"{user.id}.png").exists()
    assert not list(_dossier_temporaire.glob("*.html"))


@pytest.mark.asyncio
async def test_du_html_declare_comme_image_est_refuse(client, db, _dossier_temporaire):
    _, entetes = await _connecte(client, db)
    html = b"<html><script>alert(1)</script></html>"
    resp = await client.post(URL, files=_image(html, "photo.png", "image/png"), headers=entetes)
    assert resp.status_code == 415
    assert not list(_dossier_temporaire.iterdir())


@pytest.mark.asyncio
async def test_remplacer_une_photo_par_un_autre_format_supprime_l_ancienne(
        client, db, _dossier_temporaire):
    user, entetes = await _connecte(client, db)
    await client.post(URL, files=_image(PNG, "a.png", "image/png"), headers=entetes)
    await client.post(URL, files=_image(WEBP, "b.webp", "image/webp"), headers=entetes)
    assert (_dossier_temporaire / f"{user.id}.webp").exists()
    assert not (_dossier_temporaire / f"{user.id}.png").exists()


@pytest.mark.asyncio
async def test_l_adresse_change_a_chaque_envoi_pour_contourner_le_cache(client, db, monkeypatch):
    """Le fichier garde son nom : sans paramètre de version, le navigateur
    continuerait d'afficher l'ancienne photo."""
    _, entetes = await _connecte(client, db)
    versions = iter([1000, 2000])
    monkeypatch.setattr(agents, "_version_photo", lambda: next(versions))
    premiere = (await client.post(URL, files=_image(JPEG), headers=entetes)).json()["avatar_url"]
    seconde = (await client.post(URL, files=_image(JPEG), headers=entetes)).json()["avatar_url"]
    assert premiere != seconde
