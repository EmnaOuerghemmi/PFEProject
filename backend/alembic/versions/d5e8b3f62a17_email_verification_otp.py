"""Ajoute users.email_verification_attempts — vérification d'adresse par OTP

La vérification d'adresse passe d'un lien à usage unique à un code numérique
à 6 chiffres saisi par l'utilisateur. Un tel code se force en 10^6 essais :
il faut donc plafonner les tentatives PAR COMPTE, un plafond par IP ne servant
à rien face à un attaquant qui change d'adresse source.

La colonne `email_verification_token` est conservée telle quelle : elle porte
désormais l'empreinte HMAC du code au lieu de celle d'un jeton long.

Revision ID: d5e8b3f62a17
Revises: c4d7a2e51f88
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e8b3f62a17"
down_revision: Union[str, Sequence[str], None] = "c4d7a2e51f88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `server_default="0"` renseigne les lignes existantes ; la contrainte
    # NOT NULL serait sinon rejetée sur une table déjà peuplée.
    op.add_column(
        "users",
        sa.Column(
            "email_verification_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Les liens de vérification déjà distribués référencent des jetons longs,
    # que le nouveau parcours ne sait plus valider : on les purge pour que les
    # comptes concernés repassent proprement par « renvoyer un code ».
    op.execute(
        "UPDATE users SET email_verification_token = NULL, "
        "email_verification_expires_at = NULL "
        "WHERE email_verification_token IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "email_verification_attempts")
