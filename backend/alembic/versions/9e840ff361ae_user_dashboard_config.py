"""user dashboard config

Composition du tableau de bord, propre à chaque utilisateur.

Colonne JSON plutôt que table dédiée, sur le modèle de
`users.notification_preferences` qui existe déjà : un tableau de bord est une
préférence d'affichage, pas une donnée métier. Une table ne se justifierait que
si les graphiques devaient être partagés entre RH.

Revision ID: 9e840ff361ae
Revises: dc4602e91daf
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa


revision = "9e840ff361ae"
down_revision = "dc4602e91daf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("dashboard_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "dashboard_config")
