"""interview members (several per interview) and per-interview evaluation

Un entretien peut désormais être mené par plusieurs membres ; seuls eux
peuvent l'évaluer, et un recruteur ne voit que les entretiens dont il est
membre. Le recruteur assigné existant devient le premier membre.

L'évaluation est aussi marquée sur l'entretien lui-même : la note restant
portée par la candidature, sans cette marque un second entretien paraîtrait
déjà évalué.

Revision ID: f7c2a9d4b815
Revises: e5b8c1d47a29
Create Date: 2026-10-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7c2a9d4b815"
down_revision = "e5b8c1d47a29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_members",
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("interview_invitations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_interview_members_user_id", "interview_members", ["user_id"])
    op.execute(
        "INSERT INTO interview_members (invitation_id, user_id) "
        "SELECT id, assigned_recruiter_id FROM interview_invitations "
        "WHERE assigned_recruiter_id IS NOT NULL"
    )

    op.add_column("interview_invitations",
                  sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_invitations",
                  sa.Column("evaluated_by", postgresql.UUID(as_uuid=True),
                            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    # Entretiens déjà notés : la note de la candidature vaut pour son dernier
    # entretien confirmé.
    op.execute("""
        UPDATE interview_invitations AS inv
        SET evaluated_at = cs.updated_at
        FROM candidate_scores AS cs
        WHERE cs.application_id = inv.application_id
          AND cs.interview_score IS NOT NULL
          AND inv.status = 'CONFIRMED'
          AND inv.id = (
              SELECT i2.id FROM interview_invitations i2
              WHERE i2.application_id = inv.application_id AND i2.status = 'CONFIRMED'
              ORDER BY i2.confirmed_at DESC NULLS LAST LIMIT 1
          )
    """)


def downgrade() -> None:
    op.drop_column("interview_invitations", "evaluated_by")
    op.drop_column("interview_invitations", "evaluated_at")
    op.drop_index("ix_interview_members_user_id", table_name="interview_members")
    op.drop_table("interview_members")
