"""talent pool: candidates kept in reserve, and the offers they were invited to

Le statut « ON_HOLD » (en réserve) est une simple valeur de la colonne
`applications.status` (String) : aucune modification de schéma pour lui.

Revision ID: b8d4f1a6c392
Revises: f7c2a9d4b815
Create Date: 2026-10-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8d4f1a6c392"
down_revision = "f7c2a9d4b815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "talent_pool_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reserved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_talent_pool_entries_candidate", "talent_pool_entries", ["candidate_id"])

    op.create_table(
        "talent_pool_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_offer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("compatibility", sa.Float(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("candidate_id", "job_offer_id", name="uq_talent_pool_invitation"),
    )
    op.create_index("ix_talent_pool_invitations_candidate_sent", "talent_pool_invitations",
                    ["candidate_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_talent_pool_invitations_candidate_sent", table_name="talent_pool_invitations")
    op.drop_table("talent_pool_invitations")
    op.drop_index("ix_talent_pool_entries_candidate", table_name="talent_pool_entries")
    op.drop_table("talent_pool_entries")
