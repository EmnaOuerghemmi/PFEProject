"""add assigned_recruiter_id to interview_invitations

Revision ID: a1f3c8e20b47
Revises: b4d1e7a90c53
Create Date: 2026-09-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1f3c8e20b47"
down_revision = "b4d1e7a90c53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interview_invitations",
        sa.Column(
            "assigned_recruiter_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_invitations_assigned_recruiter",
        "interview_invitations",
        ["assigned_recruiter_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invitations_assigned_recruiter", table_name="interview_invitations")
    op.drop_column("interview_invitations", "assigned_recruiter_id")
