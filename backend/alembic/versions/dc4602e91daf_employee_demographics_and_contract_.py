"""employee demographics and contract fields

Quatre colonnes sur `employees`, toutes nullables — les fiches existantes
doivent rester valides, et personne n'est là pour les remplir au moment où
l'employé est créé (la création est automatique, à la signature du contrat).

`birth_date` et non `age` : un âge stocké en nombre devient faux au bout d'un
an et personne ne pense à le corriger. On garde la date, on calcule l'âge à
l'affichage.

`gender` reste une chaîne libre côté base, contrainte à un vocabulaire fermé
par le schéma Pydantic — même arbitrage que pour les statuts de candidature :
un ENUM PostgreSQL se paie cher dès qu'on veut l'étendre, et ce vocabulaire-là
peut évoluer.

Revision ID: dc4602e91daf
Revises: d5f9899083eb
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa


revision = "dc4602e91daf"
down_revision = "d5f9899083eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("gender", sa.String(length=20), nullable=True))
    op.add_column("employees", sa.Column("contract_type", sa.String(length=20), nullable=True))
    op.add_column("employees", sa.Column("education_level", sa.String(length=50), nullable=True))
    # Les répartitions du tableau de bord groupent sur ces deux colonnes.
    op.create_index("ix_employees_gender", "employees", ["gender"])
    op.create_index("ix_employees_birth_date", "employees", ["birth_date"])


def downgrade() -> None:
    op.drop_index("ix_employees_birth_date", table_name="employees")
    op.drop_index("ix_employees_gender", table_name="employees")
    op.drop_column("employees", "education_level")
    op.drop_column("employees", "contract_type")
    op.drop_column("employees", "gender")
    op.drop_column("employees", "birth_date")
