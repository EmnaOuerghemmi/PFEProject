"""
Sondes de santé.

- `/health`       — VIVANT : le processus répond. Sert au HEALTHCHECK Docker ;
                    ne dépend de rien d'externe, pour qu'une base momentanément
                    lente ne fasse pas redémarrer le conteneur en boucle.
- `/health/ready` — PRÊT : base joignable, schéma à la bonne révision Alembic,
                    Redis joignable. Sert au déploiement (deploy/deploy.sh) avant
                    de déclarer une version en ligne, et à la supervision via
                    `/healthz` (nginx). Répond 503 tant qu'une condition manque.

Aucune donnée sensible dans la réponse : en cas d'échec, seul le TYPE de
l'erreur est renvoyé (jamais son message, qui peut contenir une URL de base).
"""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import text

#: Schéma exactement à la révision du code.
A_JOUR = "a_jour"
#: Révision connue mais antérieure : des migrations n'ont pas été appliquées.
EN_RETARD = "en_retard"
#: Révision inconnue de ce code : une version PLUS RÉCENTE a migré la base,
#: puis on est revenu à celle-ci (retour arrière). Acceptable tant que les
#: migrations restent rétrocompatibles — règle du projet (deploy/README.md).
EN_AVANCE = "en_avance"


@lru_cache(maxsize=1)
def _scripts():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config("alembic.ini"))


async def etat_du_schema(conn) -> tuple[str, str | None, str]:
    """(état, révision de la base, révision attendue). `conn` : connexion ou session."""
    scripts = _scripts()
    attendue = scripts.get_current_head()
    courante = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    if courante == attendue:
        return A_JOUR, courante, attendue
    if courante is None:
        return EN_RETARD, None, attendue
    try:
        scripts.get_revision(courante)
    except Exception:
        return EN_AVANCE, courante, attendue
    return EN_RETARD, courante, attendue


async def verifier_disponibilite(db) -> tuple[bool, dict]:
    """Toutes les conditions pour servir du trafic. Ne lève jamais."""
    from app.cache.redis_client import get_redis

    controles: dict = {}

    try:
        await db.scalar(text("SELECT 1"))
        controles["database"] = "ok"
    except Exception as exc:
        controles["database"] = f"injoignable ({type(exc).__name__})"

    if controles["database"] == "ok":
        try:
            etat, courante, attendue = await etat_du_schema(db)
            controles["schema"] = {"etat": etat, "revision": courante, "attendue": attendue}
        except Exception as exc:
            controles["schema"] = {"etat": f"illisible ({type(exc).__name__})"}

    try:
        await (await get_redis()).ping()
        controles["redis"] = "ok"
    except Exception as exc:
        controles["redis"] = f"injoignable ({type(exc).__name__})"

    pret = (
        controles["database"] == "ok"
        and controles.get("schema", {}).get("etat") in (A_JOUR, EN_AVANCE)
        and controles["redis"] == "ok"
    )
    return pret, controles
