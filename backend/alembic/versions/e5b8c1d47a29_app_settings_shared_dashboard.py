"""create app_settings (shared dashboard composition)

Le tableau de bord n'est plus propre à chaque utilisateur : l'administrateur
le compose et choisit, graphique par graphique, qui le voit (tous, RH,
recruteurs, administrateurs). Cette composition commune vit dans une table
clé / valeur plutôt que sur la ligne d'un administrateur.

Revision ID: e5b8c1d47a29
Revises: d3a7f2c95e18
Create Date: 2026-10-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e5b8c1d47a29"
down_revision = "d3a7f2c95e18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
