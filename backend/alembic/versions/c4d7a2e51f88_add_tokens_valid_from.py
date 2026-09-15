"""Ajoute users.tokens_valid_from — révocation des jetons d'accès émis

Un JWT est autoportant : jusqu'ici, une déconnexion ou un changement de mot de
passe ne révoquait que le refresh token, et le jeton d'accès restait accepté
jusqu'à son expiration (30 min par défaut). Cette colonne porte le point de
coupure : `get_current_user` refuse tout jeton dont l'`iat` lui est antérieur.

Revision ID: c4d7a2e51f88
Revises: b7e2c9d31a45
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d7a2e51f88"
down_revision: Union[str, Sequence[str], None] = "b7e2c9d31a45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable et sans valeur par défaut : les sessions déjà ouvertes au moment
    # de la migration restent valides (NULL = aucune coupure). Seuls les
    # événements ultérieurs (logout, changement de mot de passe…) la renseignent.
    op.add_column(
        "users",
        sa.Column("tokens_valid_from", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tokens_valid_from")
