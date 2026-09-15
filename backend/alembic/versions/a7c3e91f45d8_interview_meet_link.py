"""interview_invitations : lien visio + garde-fou du rappel T-8 min

Deux colonnes portant la génération automatique d'un lien de visioconférence à
la confirmation d'un entretien :

- `meet_url` : le lien (Google Meet si la délégation domaine le permet, sinon
  une salle Jitsi Meet dérivée du token de l'invitation) ;
- `meet_reminder_sent_at` : horodatage du rappel « rejoindre maintenant »
  envoyé 8 minutes avant l'entretien — évite les doublons quand la boucle de
  fond repasse.

Aucun backfill : les invitations déjà confirmées restent sans lien et ne
déclenchent pas de rappel (la boucle ne regarde que les entretiens à venir).

Revision ID: a7c3e91f45d8
Revises: f1a4d8c62e93
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91f45d8"
down_revision: Union[str, Sequence[str], None] = "f1a4d8c62e93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interview_invitations", sa.Column("meet_url", sa.String(length=500), nullable=True))
    op.add_column(
        "interview_invitations",
        sa.Column("meet_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_invitations", "meet_reminder_sent_at")
    op.drop_column("interview_invitations", "meet_url")
