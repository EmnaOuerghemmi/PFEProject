"""
Auth endpoint tests — register, login, brute-force, refresh, 2FA, password strength.
Coverage target: 80%+
"""
import pytest
from httpx import AsyncClient

from tests.conftest import VALID_PASSWORD, WEAK_PASSWORD, USER_PAYLOAD


# ---------- Register ----------

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == USER_PAYLOAD["email"]
    assert data["role"] == "CANDIDAT"
    assert data["is_verified"] is False


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    payload = {**USER_PAYLOAD, "password": WEAK_PASSWORD, "email": "weak@example.com"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422  # Pydantic validation


# ---------- Login ----------

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": "WrongPass1!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": VALID_PASSWORD},
    )
    assert resp.status_code == 401


# ---------- Brute-force protection ----------

@pytest.mark.asyncio
async def test_bruteforce_lock(client: AsyncClient):
    """After 5 failed attempts from same IP, 429 is returned."""
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": USER_PAYLOAD["email"], "password": "WrongPass1!"},
        )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": "WrongPass1!"},
    )
    assert resp.status_code == 429


# ---------- Refresh token ----------

@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    refresh_token = login.json()["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid.token.here"})
    assert resp.status_code == 401


# ---------- Password ----------

@pytest.mark.asyncio
async def test_password_strength_validator():
    from app.core.security import validate_password_strength

    assert validate_password_strength("Test1234!") is True
    assert validate_password_strength("weak") is False
    assert validate_password_strength("alllowercase1!") is False
    assert validate_password_strength("ALLUPPERCASE1!") is False
    assert validate_password_strength("NoSpecialChar1") is False
    assert validate_password_strength("Short1!") is False


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    token = login.json()["access_token"]
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": VALID_PASSWORD, "new_password": "NewPass5678@"},
    )
    assert resp.status_code == 200


# ---------- 2FA ----------

@pytest.mark.asyncio
async def test_2fa_setup_and_enable(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Setup
    setup = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    backup_codes = setup.json()["backup_codes"]
    assert len(backup_codes) == 10

    # Enable with valid TOTP
    import pyotp
    code = pyotp.TOTP(secret).now()
    enable = await client.post("/api/v1/auth/2fa/enable", headers=headers, json={"code": code})
    assert enable.status_code == 200


@pytest.mark.asyncio
async def test_2fa_invalid_code_rejected(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": USER_PAYLOAD["email"], "password": VALID_PASSWORD},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/api/v1/auth/2fa/setup", headers=headers)
    enable = await client.post("/api/v1/auth/2fa/enable", headers=headers, json={"code": "000000"})
    assert enable.status_code == 400


@pytest.mark.asyncio
async def test_forgot_password_is_rate_limited(client: AsyncClient):
    """
    /forgot-password est plafonné à 3 appels / 10 min par IP : sans quoi la
    route permet d'énumérer les comptes et de bombarder une boîte mail.

    La 4e tentative doit être refusée avec un en-tête Retry-After exploitable
    par le client. Les compteurs sont purgés entre les tests par la fixture
    `_fresh_redis`.
    """
    payload = {"email": "inconnu@example.com"}

    for _ in range(3):
        allowed = await client.post("/api/v1/auth/forgot-password", json=payload)
        assert allowed.status_code == 200

    blocked = await client.post("/api/v1/auth/forgot-password", json=payload)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) > 0
