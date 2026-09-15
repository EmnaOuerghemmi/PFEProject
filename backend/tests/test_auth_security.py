"""
Non-régression des correctifs d'authentification.

Chaque test correspond à une faille constatée puis corrigée : ils échouent sur
le code d'avant, et documentent le comportement attendu.
"""
import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import _create_token, hash_token
from app.models.user import AuditLog, User
from tests.conftest import VALID_PASSWORD


# ─────────────────────────── Aides ───────────────────────────

async def _register(client: AsyncClient, email: str, username: str, **extra) -> None:
    payload = {"email": email, "username": username, "password": VALID_PASSWORD}
    payload.update(extra)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text


async def _verified_user(db, email: str) -> User:
    """Marque le compte comme vérifié, la vérification n'étant pas le sujet ici."""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    user.is_verified = True
    await db.commit()
    return user


async def _login(client: AsyncClient, email: str, password: str = VALID_PASSWORD) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ───────────────── #1 Escalade de privilèges ─────────────────

@pytest.mark.asyncio
async def test_inscription_publique_ne_permet_pas_de_choisir_admin(client: AsyncClient):
    """Le champ `role` du corps de requête doit être ignoré, pas honoré."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": "attaquant@example.com",
        "username": "attaquant",
        "password": VALID_PASSWORD,
        "role": "ADMIN",
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "CANDIDAT"


# ───────── #2 Persistance du verrouillage de compte ──────────

@pytest.mark.asyncio
async def test_le_compteur_d_echecs_survit_au_rollback(client: AsyncClient, db):
    """
    `get_db` annule la transaction dès qu'une exception traverse la route.
    Sans commit explicite sur le chemin d'erreur, `failed_login_attempts` et
    `locked_until` étaient perdus : le compte n'était jamais verrouillé.
    """
    await _register(client, "victime@example.com", "victime")
    await _verified_user(db, "victime@example.com")

    for _ in range(5):
        await client.post("/api/v1/auth/login", json={
            "email": "victime@example.com", "password": "MauvaisMotDePasse1!",
        })

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "victime@example.com"))).scalar_one()
    assert user.failed_login_attempts >= 5, "le compteur d'échecs n'a pas été persisté"
    assert user.locked_until is not None, "le verrouillage de compte ne s'applique pas"

    logs = (await db.execute(
        select(AuditLog).where(AuditLog.action == "LOGIN_FAIL")
    )).scalars().all()
    assert len(logs) >= 5, "les échecs de connexion ne sont pas journalisés"


# ──────────── #3 Consommation des codes de secours ───────────

@pytest.mark.asyncio
async def test_un_code_de_secours_ne_sert_qu_une_fois(client: AsyncClient, db):
    """
    Muter en place la liste portée par la colonne JSON ne déclenchait aucune
    écriture : le même code restait valable indéfiniment.
    """
    await _register(client, "bob@example.com", "bob")
    await _verified_user(db, "bob@example.com")
    tokens = await _login(client, "bob@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    setup = await client.post("/api/v1/auth/2fa/setup", json={}, headers=headers)
    secret, codes = setup.json()["secret"], setup.json()["backup_codes"]
    await client.post("/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers)

    corps = {"email": "bob@example.com", "password": VALID_PASSWORD, "code": codes[0]}
    premier = await client.post("/api/v1/auth/2fa/backup", json=corps)
    second = await client.post("/api/v1/auth/2fa/backup", json=corps)

    assert premier.status_code == 200, premier.text
    assert second.status_code == 401, "le code de secours est réutilisable"

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "bob@example.com"))).scalar_one()
    assert len(user.totp_backup_codes) == 9


@pytest.mark.asyncio
async def test_code_de_secours_utilisable_sans_jeton_d_acces(client: AsyncClient, db):
    """
    L'ancienne route exigeait d'être authentifié — donc inatteignable, puisque
    le code de secours sert précisément quand on ne peut pas se connecter.
    """
    await _register(client, "carol@example.com", "carol")
    await _verified_user(db, "carol@example.com")
    tokens = await _login(client, "carol@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    setup = await client.post("/api/v1/auth/2fa/setup", json={}, headers=headers)
    secret, codes = setup.json()["secret"], setup.json()["backup_codes"]
    await client.post("/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers)

    # Aucun en-tête Authorization : c'est tout l'intérêt.
    resp = await client.post("/api/v1/auth/2fa/backup", json={
        "email": "carol@example.com", "password": VALID_PASSWORD, "code": codes[0],
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ──────── #5 /refresh sur un compte désactivé ────────

@pytest.mark.asyncio
async def test_refresh_refuse_un_compte_desactive(client: AsyncClient, db):
    await _register(client, "licencie@example.com", "licencie")
    user = await _verified_user(db, "licencie@example.com")
    tokens = await _login(client, "licencie@example.com")

    user.is_active = False
    await db.commit()

    resp = await client.post("/api/v1/auth/refresh",
                             json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code in (401, 403), "un compte désactivé renouvelle encore ses jetons"


# ──────── #6 Google : compte désactivé et adresse non vérifiée ────────

@pytest.mark.asyncio
async def test_google_refuse_un_compte_desactive(client: AsyncClient, db, monkeypatch):
    from app.services import report_service

    async def faux_jeton(self, id_token):
        return {"sub": "google-1", "email": "dave@example.com", "name": "Dave",
                "email_verified": True, "iss": "accounts.google.com", "aud": "x"}

    monkeypatch.setattr(report_service.AuthService, "_verify_google_token", faux_jeton)

    await _register(client, "dave@example.com", "dave")
    user = await _verified_user(db, "dave@example.com")
    user.is_active = False
    await db.commit()

    resp = await client.post("/api/v1/auth/google", json={"id_token": "peu-importe"})
    assert resp.status_code == 403, "la porte OAuth contourne la désactivation du compte"


@pytest.mark.asyncio
async def test_google_refuse_une_adresse_non_verifiee(client: AsyncClient, monkeypatch):
    """
    Sans ce contrôle, un fournisseur tiers peut revendiquer l'adresse d'autrui
    et se voir rattacher le compte local correspondant.
    """
    from app.services import report_service

    async def faux_jeton(self, id_token):
        return {"sub": "google-2", "email": "usurpe@example.com", "name": "X",
                "email_verified": False, "iss": "accounts.google.com", "aud": "x"}

    monkeypatch.setattr(report_service.AuthService, "_verify_google_token", faux_jeton)

    resp = await client.post("/api/v1/auth/google", json={"id_token": "peu-importe"})
    assert resp.status_code == 401


# ──────── #7 `sub` non conforme ────────

@pytest.mark.asyncio
async def test_jeton_avec_sub_non_uuid_renvoie_401(client: AsyncClient):
    """`UUID(...)` hors du try remontait en ValueError, soit une erreur 500."""
    from datetime import timedelta

    jeton = _create_token(
        {"sub": "pas-un-uuid", "role": "ADMIN", "permissions": {}, "type": "access"},
        timedelta(minutes=5),
    )
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {jeton}"})
    assert resp.status_code == 401


# ──────── #8 Réinitialisation de mot de passe ────────

@pytest.mark.asyncio
async def test_le_jeton_de_reinitialisation_n_est_pas_stocke_en_clair(client: AsyncClient, db):
    await _register(client, "erin@example.com", "erin")
    await client.post("/api/v1/auth/forgot-password", json={"email": "erin@example.com"})

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "erin@example.com"))).scalar_one()
    assert user.password_reset_token is not None
    # Une empreinte HMAC-SHA256 : 64 caractères hexadécimaux, jamais le jeton lui-même.
    assert len(user.password_reset_token) == 64
    assert int(user.password_reset_token, 16) >= 0


@pytest.mark.asyncio
async def test_la_reinitialisation_aboutit_sans_erreur_500(client: AsyncClient, db):
    """
    La comparaison entre datetime naïve (SQLite) et consciente du fuseau
    levait un TypeError : la route répondait 500 au lieu de réinitialiser.
    """
    from app.core.security import generate_secure_token

    await _register(client, "frank@example.com", "frank")
    user = (await db.execute(select(User).where(User.email == "frank@example.com"))).scalar_one()

    jeton = generate_secure_token()
    user.password_reset_token = hash_token(jeton)
    from datetime import datetime, timedelta, timezone
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    resp = await client.post("/api/v1/auth/reset-password",
                             json={"token": jeton, "new_password": "AutreMdp123!"})
    assert resp.status_code == 200, resp.text


# ──────── #10 Ordre des routes ────────

@pytest.mark.asyncio
async def test_route_audit_logs_non_masquee(client: AsyncClient, db):
    """`/users/audit-logs` était capté par `/users/{user_id}` et finissait en 422."""
    await _register(client, "admin@example.com", "adminuser")
    user = await _verified_user(db, "admin@example.com")
    user.role = "ADMIN"
    await db.commit()

    tokens = await _login(client, "admin@example.com")
    resp = await client.get("/api/v1/users/audit-logs",
                            headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()


# ──────── #11 Réinitialisation d'une 2FA active ────────

@pytest.mark.asyncio
async def test_reinitialiser_une_2fa_active_exige_un_code(client: AsyncClient, db):
    """Un jeton volé ne doit pas suffire à remplacer le second facteur."""
    await _register(client, "grace@example.com", "grace")
    await _verified_user(db, "grace@example.com")
    tokens = await _login(client, "grace@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    setup = await client.post("/api/v1/auth/2fa/setup", json={}, headers=headers)
    secret = setup.json()["secret"]
    await client.post("/api/v1/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers)

    sans_code = await client.post("/api/v1/auth/2fa/setup", json={}, headers=headers)
    assert sans_code.status_code == 400

    avec_code = await client.post("/api/v1/auth/2fa/setup",
                                  json={"current_code": pyotp.TOTP(secret).now()}, headers=headers)
    assert avec_code.status_code == 200
    assert avec_code.json()["secret"] != secret

    # La protection est suspendue jusqu'à confirmation : sans cela, abandonner
    # en cours de route enfermerait l'utilisateur dehors.
    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "grace@example.com"))).scalar_one()
    assert user.totp_enabled is False


# ──────── #13 Révocation des jetons d'accès ────────

@pytest.mark.asyncio
async def test_le_jeton_d_acces_meurt_avec_la_deconnexion(client: AsyncClient, db):
    await _register(client, "henri@example.com", "henri")
    await _verified_user(db, "henri@example.com")
    tokens = await _login(client, "henri@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204

    apres = await client.get("/api/v1/users/me", headers=headers)
    assert apres.status_code == 401, "le jeton reste valable après la déconnexion"


@pytest.mark.asyncio
async def test_le_changement_de_mot_de_passe_coupe_les_sessions(client: AsyncClient, db):
    await _register(client, "iris@example.com", "iris")
    await _verified_user(db, "iris@example.com")
    tokens = await _login(client, "iris@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post("/api/v1/auth/change-password", headers=headers,
                             json={"current_password": VALID_PASSWORD, "new_password": "AutreMdp123!"})
    assert resp.status_code == 200

    apres = await client.get("/api/v1/users/me", headers=headers)
    assert apres.status_code == 401


# ──────── #19 / OTP : vérification d'adresse par code ────────

@pytest.mark.asyncio
async def test_le_code_de_verification_ouvre_la_session(client: AsyncClient, db):
    """
    Parcours complet : inscription → code par e-mail → session ouverte.
    C'est ce qui permet à l'écran de saisie de rediriger vers l'accueil.
    """
    await _register(client, "jade@example.com", "jade")

    # Le code ne circule que dans l'e-mail : on relit son empreinte pour
    # retrouver la valeur, ce que seul un test peut se permettre.
    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "jade@example.com"))).scalar_one()
    assert user.is_verified is False
    assert user.email_verification_token is not None

    code = next(f"{n:06d}" for n in range(1_000_000)
                if hash_token(f"{n:06d}") == user.email_verification_token)

    resp = await client.post("/api/v1/auth/verify-email",
                             json={"email": "jade@example.com", "code": code})
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "jade@example.com"))).scalar_one()
    assert user.is_verified is True
    assert user.email_verification_token is None


@pytest.mark.asyncio
async def test_le_code_de_verification_est_plafonne_en_tentatives(client: AsyncClient, db):
    """
    Six chiffres se forcent en 10^6 essais : le plafond par COMPTE est la seule
    protection efficace, un attaquant pouvant changer d'adresse IP.
    """
    await _register(client, "karim@example.com", "karim")

    for _ in range(5):
        resp = await client.post("/api/v1/auth/verify-email",
                                 json={"email": "karim@example.com", "code": "000000"})
        assert resp.status_code in (400, 429)

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "karim@example.com"))).scalar_one()
    assert user.email_verification_attempts >= 5, "le compteur de tentatives est annulé par le rollback"

    epuise = await client.post("/api/v1/auth/verify-email",
                               json={"email": "karim@example.com", "code": "000000"})
    assert epuise.status_code == 429


@pytest.mark.asyncio
async def test_renvoyer_un_code_reinitialise_les_tentatives(client: AsyncClient, db):
    """Sinon un compte ayant épuisé son quota resterait bloqué définitivement."""
    await _register(client, "lina@example.com", "lina")

    for _ in range(5):
        await client.post("/api/v1/auth/verify-email",
                          json={"email": "lina@example.com", "code": "000000"})

    resp = await client.post("/api/v1/auth/resend-verification", json={"email": "lina@example.com"})
    assert resp.status_code == 200

    db.expire_all()
    user = (await db.execute(select(User).where(User.email == "lina@example.com"))).scalar_one()
    assert user.email_verification_attempts == 0


@pytest.mark.asyncio
async def test_renvoyer_un_code_ne_revele_pas_les_adresses_connues(client: AsyncClient):
    """Réponse identique pour une adresse inconnue : pas d'énumération."""
    resp = await client.post("/api/v1/auth/resend-verification",
                             json={"email": "personne@example.com"})
    assert resp.status_code == 200
