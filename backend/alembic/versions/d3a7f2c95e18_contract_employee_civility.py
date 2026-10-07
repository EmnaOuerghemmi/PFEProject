"""add employee_civility to contracts

Civilité du salarié (« M. » / « Mme ») : le contrat de travail l'écrit en
toutes lettres et accorde « né / née », « demeurant », etc. Sans elle, le PDF
devait écrire « M./Mme … né(e) », ce qu'aucun contrat réel ne contient.

Revision ID: d3a7f2c95e18
Revises: c7e2b9f41a08
Create Date: 2026-10-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d3a7f2c95e18"
down_revision = "c7e2b9f41a08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contracts",
        sa.Column("employee_civility", sa.String(length=5), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contracts", "employee_civility")
