"""candidate score visibility flags

Deux drapeaux sur `candidate_scores`, décidés par le RH candidature par
candidature :

* `test_score_visible` — le candidat peut voir la note de son test technique.
* `interview_feedback_visible` — le candidat peut voir le retour d'entretien.

**Faux par défaut, et c'est le point important.** Le candidat ne voit rien, et
surtout rien ne lui indique qu'il existe quelque chose à voir : la section
n'apparaît pas du tout. Un « votre recruteur n'a pas partagé cette note »
transformerait chaque candidature en demande de partage.

`server_default` à `false` plutôt qu'un simple `default` Python : les lignes
déjà en base doivent être fermées, et une valeur par défaut côté application ne
les aurait pas touchées.

Revision ID: 30f9766c7214
Revises: 9e840ff361ae
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa


revision = "30f9766c7214"
down_revision = "9e840ff361ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_scores",
        sa.Column("test_score_visible", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "candidate_scores",
        sa.Column("interview_feedback_visible", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    # Message écrit par le RH à l'intention du candidat, facultatif. Distinct de
    # `interview_notes`, qui reste interne : des observations prises pour soi ne
    # se relisent pas de la même façon qu'un retour adressé à quelqu'un.
    op.add_column(
        "candidate_scores",
        sa.Column("candidate_feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_scores", "candidate_feedback")
    op.drop_column("candidate_scores", "interview_feedback_visible")
    op.drop_column("candidate_scores", "test_score_visible")
