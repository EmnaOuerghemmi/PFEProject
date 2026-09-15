from datetime import datetime, timezone

from fastapi import Request


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def utcnow() -> datetime:
    """Instant courant, toujours conscient du fuseau."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """
    Ramène une datetime lue en base à une valeur consciente du fuseau (UTC).

    PostgreSQL restitue des datetimes « aware » sur les colonnes
    `DateTime(timezone=True)`, SQLite des datetimes « naïves ». Comparer les
    deux lève `TypeError: can't compare offset-naive and offset-aware
    datetimes` — ce qui transformait toute réinitialisation de mot de passe en
    erreur 500 sur SQLite. On normalise donc systématiquement avant comparaison,
    en considérant qu'une valeur naïve est déjà exprimée en UTC (c'est ce que
    l'application écrit).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def paginate(page: int, size: int) -> tuple[int, int]:
    """Returns (offset, limit) for SQL queries."""
    return (page - 1) * size, size
