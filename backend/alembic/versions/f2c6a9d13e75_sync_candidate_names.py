"""realign candidate names with account names

`candidates.full_name` était copié du compte à l'inscription, puis jamais mis à
jour : un candidat qui changeait son nom restait affiché sous l'ancien dans les
candidatures, le classement et les contrats. Le service synchronise désormais
les deux à chaque modification ; cette migration rattrape les dossiers déjà
désynchronisés. Le nom du COMPTE fait foi.

Revision ID: f2c6a9d13e75
Revises: b8d4f1a6c392
Create Date: 2026-10-08 00:00:00.000000
"""
from alembic import op

revision = "f2c6a9d13e75"
down_revision = "b8d4f1a6c392"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE candidates AS c
           SET full_name = TRIM(u.full_name)
          FROM users AS u
         WHERE u.id = c.user_id
           AND u.full_name IS NOT NULL
           AND TRIM(u.full_name) <> ''
           AND c.full_name IS DISTINCT FROM TRIM(u.full_name)
        """
    )


def downgrade() -> None:
    # Les anciens noms ne sont pas conservés : rien à restaurer.
    pass
