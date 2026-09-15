import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, validate_password_strength
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


async def init_superadmin(db: AsyncSession, email: str, username: str, password: str) -> User | None:
    """
    Crée le compte superadmin s'il n'existe pas déjà.

    Ne fait rien si l'adresse ou le mot de passe n'est pas configuré : ces
    valeurs proviennent désormais de l'environnement (SUPERADMIN_EMAIL /
    SUPERADMIN_PASSWORD) et non plus du code, où elles se retrouvaient
    publiées dans l'historique Git.
    """
    from sqlalchemy import select

    if not email or not password:
        logger.info(
            "Superadmin non créé : renseignez SUPERADMIN_EMAIL et SUPERADMIN_PASSWORD "
            "dans l'environnement pour l'activer."
        )
        return None

    if not validate_password_strength(password):
        logger.error(
            "Superadmin non créé : SUPERADMIN_PASSWORD ne respecte pas la politique "
            "(8 caractères minimum, majuscule, minuscule, chiffre et caractère spécial)."
        )
        return None

    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=True,
        is_verified=True,
        role=UserRole.ADMIN,
        full_name="Super Admin",
        permissions={},
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
