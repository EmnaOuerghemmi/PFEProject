"""Renomme les rôles vers le vocabulaire métier (ADMIN, RH, RECRUTEUR, CANDIDAT)

`users.role` est une colonne texte libre, pas un ENUM PostgreSQL : le
renommage est donc un simple UPDATE, sans recréation de type ni verrou long.

Les comptes existants gardent exactement les mêmes droits — seule l'étiquette
change :
  RH_MANAGER → RH          (inchangé fonctionnellement)
  RH_STAFF   → RECRUTEUR   (ses permissions évoluent, mais par la POLITIQUE
                            Casbin, pas par cette migration)
  READ_ONLY  → CANDIDAT

La descente rétablit les anciens noms : une base restaurée sur une version
antérieure du code doit retrouver des rôles que ce code sait lire.

Revision ID: b4d1e7a90c53
Revises: 30f9766c7214
"""
from alembic import op
import sqlalchemy as sa


revision = "b4d1e7a90c53"
down_revision = "30f9766c7214"
branch_labels = None
depends_on = None


#: (ancien, nouveau) — l'ordre n'a pas d'importance, aucun nom n'est la cible
#: d'un autre (pas d'effet domino type A→B puis B→C).
_RENOMMAGES = [
    ("RH_MANAGER", "RH"),
    ("RH_STAFF", "RECRUTEUR"),
    ("READ_ONLY", "CANDIDAT"),
]


def _appliquer(paires: list[tuple[str, str]]) -> None:
    for source, cible in paires:
        op.execute(
            sa.text("UPDATE users SET role = :cible WHERE role = :source")
            .bindparams(cible=cible, source=source)
        )


def upgrade() -> None:
    _appliquer(_RENOMMAGES)


def downgrade() -> None:
    _appliquer([(cible, source) for source, cible in _RENOMMAGES])
