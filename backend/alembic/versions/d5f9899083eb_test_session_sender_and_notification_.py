"""test session sender and notification guard

Deux colonnes sur `test_sessions`, toutes deux nécessaires à l'alerte de fin de
test envoyée au RH :

* `sent_by` — quel RH a envoyé ce test. Sans elle, on ne saurait prévenir que
  « tous les administrateurs », ce qui noie le destinataire concerné. Même rôle
  que `created_by` sur les invitations d'entretien.
* `notified_at` — garde-fou d'idempotence. La boucle de balayage repasse toutes
  les deux minutes ; sans cette marque, une session re-notée renverrait le
  courriel à chaque passage. Même rôle que `meet_reminder_sent_at` sur les
  invitations.

`sent_by` est en `SET NULL` à la suppression : un RH qui quitte l'entreprise ne
doit pas emporter l'historique des tests avec lui.

Revision ID: d5f9899083eb
Revises: 904698f9bf8c
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d5f9899083eb"
down_revision = "904698f9bf8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_sessions",
        sa.Column("sent_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_test_sessions_sent_by_users",
        "test_sessions", "users",
        ["sent_by"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "test_sessions",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Le balayage cherche exactement ces lignes toutes les deux minutes :
    # terminées et pas encore annoncées.
    op.create_index(
        "ix_test_sessions_notification_due",
        "test_sessions",
        ["submitted_at", "notified_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_test_sessions_notification_due", table_name="test_sessions")
    op.drop_column("test_sessions", "notified_at")
    op.drop_constraint(
        "fk_test_sessions_sent_by_users", "test_sessions", type_="foreignkey"
    )
    op.drop_column("test_sessions", "sent_by")
