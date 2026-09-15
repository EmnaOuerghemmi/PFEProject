"""CV de profil du candidat et prétention salariale par candidature

Trois colonnes, toutes nullables — aucune donnée existante n'est invalidée :

* `candidates.cv_filename` / `candidates.cv_uploaded_at` complètent la colonne
  `cv_path`, jusqu'ici déclarée dans le modèle mais jamais écrite. Le CV devient
  une pièce du profil, déposable à l'inscription ou plus tard.
* `applications.expected_salary` porte la prétention annoncée pour CETTE offre,
  en TND mensuels bruts. Facultative par construction : elle est demandée après
  l'envoi du dossier et peut être passée.

Revision ID: 9d39b20b68bf
Revises: a7c3e91f45d8
"""
from alembic import op
import sqlalchemy as sa


revision = "9d39b20b68bf"
down_revision = "a7c3e91f45d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("cv_filename", sa.String(length=255), nullable=True))
    op.add_column("candidates", sa.Column("cv_uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("expected_salary", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "expected_salary")
    op.drop_column("candidates", "cv_uploaded_at")
    op.drop_column("candidates", "cv_filename")
