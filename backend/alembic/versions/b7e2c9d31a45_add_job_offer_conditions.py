"""add work_mode, contract_type, status and expires_at to job_offers

Conditions du poste saisies à la création d'une offre :
  - `work_mode`     : ON_SITE | HYBRID | REMOTE
  - `contract_type` : CDI | CDD | SIVP | STAGE | FREELANCE
  - `status`        : DRAFT | PUBLISHED | CLOSED
  - `expires_at`    : date limite de candidature (NULL = sans limite)

`status` est NOT NULL avec un `server_default` à 'PUBLISHED' : les offres
existantes étaient toutes visibles côté candidat, cette valeur préserve donc
leur comportement au lieu de les faire disparaître du frontoffice.

Revision ID: b7e2c9d31a45
Revises: a3f8c1d94b62
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c9d31a45"
down_revision: Union[str, Sequence[str], None] = "a3f8c1d94b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_offers", sa.Column("work_mode", sa.String(length=20), nullable=True))
    op.add_column("job_offers", sa.Column("contract_type", sa.String(length=20), nullable=True))
    op.add_column(
        "job_offers",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PUBLISHED"),
    )
    op.add_column(
        "job_offers",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_offers_status", "job_offers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_job_offers_status", table_name="job_offers")
    op.drop_column("job_offers", "expires_at")
    op.drop_column("job_offers", "status")
    op.drop_column("job_offers", "contract_type")
    op.drop_column("job_offers", "work_mode")
