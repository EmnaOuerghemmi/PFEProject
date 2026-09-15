"""job_offers.contract_type (unique) → contract_types (liste)

Une offre peut légitimement ouvrir sur plusieurs formes de contrat — un même
poste proposé « SIVP ou CDD » est courant en Tunisie. La colonne unique
obligeait à publier deux offres jumelles pour exprimer ce choix.

Les valeurs existantes sont reportées telles quelles dans un tableau à un
élément : aucune offre ne perd son type.

Revision ID: f1a4d8c62e93
Revises: e6f9c4a73b21
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a4d8c62e93"
down_revision: Union[str, Sequence[str], None] = "e6f9c4a73b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_offers", sa.Column("contract_types", sa.JSON(), nullable=True))

    # Report des valeurs : 'CDI' devient '["CDI"]'.
    #
    # PostgreSQL est strictement typé et refuse d'affecter une expression `text`
    # à une colonne `json` sans transtypage explicite ; SQLite, lui, stocke le
    # JSON en TEXT et n'a pas de CAST vers « json » (il lui appliquerait une
    # affinité NUMERIC, ce qui écraserait la valeur par 0). D'où l'aiguillage.
    if op.get_bind().dialect.name == "postgresql":
        expression = """CAST('["' || contract_type || '"]' AS json)"""
    else:
        expression = """'["' || contract_type || '"]'"""

    op.execute(
        f"""
        UPDATE job_offers
           SET contract_types = {expression}
         WHERE contract_type IS NOT NULL AND contract_type <> ''
        """
    )

    op.drop_column("job_offers", "contract_type")


def downgrade() -> None:
    op.add_column("job_offers", sa.Column("contract_type", sa.String(20), nullable=True))

    # Le retour arrière ne peut garder qu'une valeur : on conserve la première
    # de la liste, les éventuelles suivantes sont perdues — c'est la nature même
    # de la colonne unique qu'on restaure.
    #
    # Chaque moteur a son extracteur d'élément JSON ; aucun n'est portable, et
    # les découper à coups de `substr` serait bien plus fragile que d'aiguiller.
    if op.get_bind().dialect.name == "postgresql":
        extraction = "contract_types->>0"
    else:
        extraction = "json_extract(contract_types, '$[0]')"

    op.execute(
        f"""
        UPDATE job_offers
           SET contract_type = {extraction}
         WHERE contract_types IS NOT NULL
        """
    )

    op.drop_column("job_offers", "contract_types")
