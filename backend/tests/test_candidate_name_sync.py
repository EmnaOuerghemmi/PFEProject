"""
Le nom du compte fait foi : le dossier candidat le suit.

Avant, `candidates.full_name` était copié à l'inscription et jamais mis à
jour — un candidat renommé restait affiché sous son ancien nom dans les
candidatures, le classement et les contrats.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.recruitment import Candidate
from app.models.user import User, UserRole
from tests.conftest import VALID_PASSWORD


@pytest.mark.asyncio
async def test_renommer_le_compte_renomme_le_dossier_candidat(client: AsyncClient, db: AsyncSession):
    email = f"cand_{uuid.uuid4().hex[:6]}@exemple.tn"
    user = User(id=uuid.uuid4(), email=email, username=email.split("@")[0],
                hashed_password=hash_password(VALID_PASSWORD), full_name="Ancien Nom",
                role=UserRole.CANDIDAT, is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    db.add(Candidate(id=uuid.uuid4(), user_id=user.id, full_name="Ancien Nom"))
    await db.commit()

    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})).json()["access_token"]
    resp = await client.patch("/api/v1/users/me", json={"full_name": "Nouveau Nom"},
                              headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text

    db.expire_all()
    candidat = (await db.execute(select(Candidate).where(Candidate.user_id == user.id))).scalar_one()
    assert candidat.full_name == "Nouveau Nom"
