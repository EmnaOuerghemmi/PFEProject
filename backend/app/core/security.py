import re
import secrets
import string
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
import bcrypt
from jose import jwt

from app.core.config import settings

# We call the `bcrypt` library directly instead of going through passlib's
# CryptContext: recent bcrypt (4.x) dropped the `__about__` attribute that
# passlib 1.7.x probes during backend init, which made passlib crash on the
# very first hash. Direct bcrypt produces the same `$2b$` hashes, so existing
# stored hashes remain verifiable.

_BCRYPT_MAX_BYTES = 72

PASSWORD_REGEX = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,}$"
)


# ---------- Password ----------

def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password cannot be longer than 72 bytes.")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    pw = plain.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Empreinte jetable, calculée une seule fois au chargement du module, servant à
# égaliser le temps de réponse de /login. Sans elle, une adresse inconnue rend
# la main sans qu'aucun bcrypt ne soit calculé : l'écart de latence (~250 ms à
# 12 tours) suffit à énumérer les comptes existants.
_DUMMY_HASH = bcrypt.hashpw(b"piqbit-timing-equalizer", bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def dummy_verify_password(plain: str) -> None:
    """Consomme le même temps CPU qu'un `verify_password` réel, sans rien dire."""
    verify_password(plain, _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    if not token_hash:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)


def validate_password_strength(password: str) -> bool:
    """Enforces: 8+ chars, uppercase, lowercase, digit, special char."""
    return len(password.encode("utf-8")) <= 72 and bool(PASSWORD_REGEX.match(password))


# ---------- JWT ----------

def _create_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str, role: str, permissions: dict) -> str:
    return _create_token(
        {"sub": user_id, "role": role, "permissions": permissions, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ---------- TOTP / 2FA ----------

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.TOTP_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(count: int = 10) -> list[str]:
    """Returns plain codes. Caller must hash before storing."""
    alphabet = string.ascii_uppercase + string.digits
    return ["".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(count)]


def hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode("utf-8")


def verify_backup_code(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------- Tokens (email / reset) ----------

def generate_secure_token(length: int = 64) -> str:
    return secrets.token_urlsafe(length)


def generate_otp_code(length: int = 6) -> str:
    """
    Code numérique à usage unique, destiné à être saisi à la main.

    `secrets.randbelow` et non `random` : ce dernier s'appuie sur un Mersenne
    Twister dont l'état se reconstitue à partir de quelques tirages, ce qui
    rendrait les codes suivants prévisibles. Les zéros de tête sont conservés,
    d'où le formatage sur une largeur fixe.
    """
    return f"{secrets.randbelow(10 ** length):0{length}d}"
