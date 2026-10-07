"""
Retour de Google après la liaison d'un compte Meet.

La route plantait (500) avant d'enregistrer le jeton : `asyncio` n'était pas
importé dans le module. Conséquence en cascade : aucun compte n'était jamais
lié, et « Créer le lien » répondait ensuite 409 (« Aucun compte Google lié »).

L'échange du code avec Google est simulé : aucun appel réseau.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google_meet import google_meet_client
from app.models.user import User, UserRole

URL = "/api/v1/interview/google-meet/callback"


async def _utilisateur(db: AsyncSession) -> uuid.UUID:
    suffixe = uuid.uuid4().hex[:6]
    user = User(id=uuid.uuid4(), email=f"meet_{suffixe}@example.com", username=f"meet_{suffixe}",
                hashed_password="x", full_name="RH Meet", role=UserRole.RH,
                is_active=True, is_verified=True)
    db.add(user)
    await db.commit()
    return user.id


@pytest.mark.asyncio
async def test_le_jeton_google_est_enregistre(client: AsyncClient, db: AsyncSession, monkeypatch):
    user_id = await _utilisateur(db)
    monkeypatch.setattr(google_meet_client, "echanger_code", lambda code: "jeton-de-test")

    resp = await client.get(URL, params={"code": "c", "state": str(user_id)}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].endswith("google_meet=connected")
    db.expire_all()
    jeton = (await db.execute(select(User.google_meet_refresh_token).where(User.id == user_id))).scalar()
    assert jeton == "jeton-de-test"


@pytest.mark.asyncio
async def test_sans_jeton_de_rafraichissement_on_redirige_sans_planter(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    user_id = await _utilisateur(db)
    monkeypatch.setattr(google_meet_client, "echanger_code", lambda code: None)

    resp = await client.get(URL, params={"code": "c", "state": str(user_id)}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].endswith("google_meet=no_refresh_token")


@pytest.mark.asyncio
async def test_un_refus_de_google_redirige_vers_l_erreur(client: AsyncClient):
    resp = await client.get(URL, params={"error": "access_denied"}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"].endswith("google_meet=error")
