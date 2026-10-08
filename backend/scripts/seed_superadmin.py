"""
Run: python -m scripts.seed_superadmin
Creates the superadmin user if not already present.
"""
import asyncio
import sys
import os

# psycopg3 async requires SelectorEventLoop on Windows (not ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.init_db import init_superadmin

# Identifiants lus dans l'environnement (backend/.env), jamais dans le code :
# le dépôt est public, et un mot de passe poussé y reste lisible dans
# l'historique même après suppression.


async def main() -> None:
    from app.db.session import engine
    from app.db.base import Base
    from app.models.user import User, AuditLog  # noqa: F401 — register models with Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if not settings.SUPERADMIN_EMAIL or not settings.SUPERADMIN_PASSWORD:
        print("[ERREUR] Renseignez SUPERADMIN_EMAIL et SUPERADMIN_PASSWORD dans backend/.env.")
        raise SystemExit(1)

    async with AsyncSessionLocal() as db:
        user = await init_superadmin(
            db,
            email=settings.SUPERADMIN_EMAIL,
            username=settings.SUPERADMIN_USERNAME,
            password=settings.SUPERADMIN_PASSWORD,
        )
        if user:
            print(f"[OK] SuperAdmin ready: {user.email} (id={user.id})")
        else:
            print("[SKIP] SuperAdmin already exists.")


if __name__ == "__main__":
    asyncio.run(main())
