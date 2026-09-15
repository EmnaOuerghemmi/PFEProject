from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.utils.helpers import get_client_ip

# `tokenUrl` désigne la route que Swagger appelle depuis le bouton « Authorize ».
# Elle doit accepter un formulaire OAuth2 (`username`/`password`), ce que
# /auth/login — qui attend du JSON — ne fait pas : d'où la route dédiée
# /auth/token, qui délègue au même service.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")

# L'IP réelle de l'appelant est lue via `get_client_ip` (app/utils/helpers.py),
# qui tient compte de X-Forwarded-For : derrière le reverse-proxy nginx,
# `request.client.host` vaut l'IP du conteneur proxy, si bien que tous les
# utilisateurs partageraient un même compteur de limitation.
client_ip = get_client_ip


def rate_limit(scope: str, limit: int, window_seconds: int):
    """
    Fabrique une dépendance FastAPI limitant une route par IP.

    Usage :
        @router.post("/forgot-password",
                     dependencies=[Depends(rate_limit("forgot_password", 3, 600))])

    Renvoie 429 avec un en-tête `Retry-After` quand le quota est dépassé.
    """
    from app.cache.redis_client import hit_rate_limit

    async def _dependency(request: Request) -> None:
        allowed, retry_after = await hit_rate_limit(
            scope, client_ip(request), limit, window_seconds
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Trop de tentatives. Réessayez dans "
                    f"{max(retry_after // 60, 1)} minute(s)."
                ),
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        # `UUID(...)` était hors du `try` : un `sub` non conforme (jeton forgé,
        # jeton d'une autre application) remontait en ValueError non capturée,
        # soit une erreur 500 au lieu du 401 attendu.
        user_id = UUID(str(payload.get("sub")))
    except (JWTError, ValueError, TypeError, AttributeError):
        raise credentials_exception

    from sqlalchemy import select

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    # Un JWT reste valable jusqu'à son `exp`, même après une déconnexion ou un
    # changement de mot de passe. `tokens_valid_from` porte le point de coupure
    # posé par ces événements : tout jeton antérieur est refusé.
    if user.is_token_revoked(payload.get("iat")):
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Compte désactivé.")
    if user.is_locked:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Compte temporairement verrouillé.")

    return user


# Variante tolérante du schéma ci-dessus : `auto_error=False` renvoie None au
# lieu de lever un 401 quand l'en-tête Authorization est absent. Indispensable
# pour les routes MIXTES, lisibles par un visiteur anonyme mais qui montrent
# davantage à un utilisateur habilité.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token", auto_error=False)


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """
    Identifie l'appelant s'il est connecté, sans jamais refuser l'accès.

    Un jeton absent, expiré ou invalide donne None — la route reste servie,
    à charge pour elle d'adapter ce qu'elle expose. Ne jamais l'employer pour
    protéger une ressource : c'est `get_current_user` qui refuse.
    """
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


# Le contrôle par rôle vit maintenant dans `app.core.rbac` (Casbin) : la
# politique est un fichier, pas une liste de rôles répétée dans chaque
# endpoint. `require_permission` et les alias `AdminOnly` /
# `HRManagerOrAbove` n'étaient référencés nulle part et sont partis avec.
