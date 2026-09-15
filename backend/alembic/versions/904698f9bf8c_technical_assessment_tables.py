"""Test technique : vivier de questions, sessions, réponses

Trois tables neuves et six colonnes sur `candidate_scores`, toutes nullables :
aucune candidature existante n'est invalidée, elles se retrouvent simplement
sans volet test ni volet entretien — état normal, pas une erreur.

Les types énumérés sont créés explicitement plutôt que laissés à
`sa.Enum(...)` dans `create_table` : sous PostgreSQL, un type créé implicitement
n'est pas supprimé au `downgrade`, et la migration cesse d'être réversible.
SQLite ignore les types nommés, d'où le garde sur le dialecte.

Revision ID: 904698f9bf8c
Revises: 9d39b20b68bf
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "904698f9bf8c"
down_revision = "9d39b20b68bf"
branch_labels = None
depends_on = None


_ENUMS = {
    "question_difficulty": ("FACILE", "MOYENNE", "DIFFICILE"),
    "question_kind": ("QCM_UNIQUE", "QCM_MULTIPLE", "REPONSE_COURTE"),
    "question_status": ("GENEREE", "VALIDEE", "ACTIVE", "RETIREE"),
    "test_session_status": ("ENVOYE", "EN_COURS", "TERMINE", "EXPIRE", "ABANDONNE"),
    "answer_outcome": ("CORRECTE", "FAUSSE", "PASSEE", "NON_ATTEINTE"),
}


def _enum(nom: str) -> sa.Enum:
    """Référence un type déjà créé — `create_type=False` évite un doublon."""
    return postgresql.ENUM(*_ENUMS[nom], name=nom, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"

    if postgres:
        for nom, valeurs in _ENUMS.items():
            postgresql.ENUM(*valeurs, name=nom).create(bind, checkfirst=True)

    difficulty = _enum("question_difficulty") if postgres else sa.Enum(
        *_ENUMS["question_difficulty"], name="question_difficulty")
    kind = _enum("question_kind") if postgres else sa.Enum(
        *_ENUMS["question_kind"], name="question_kind")
    qstatus = _enum("question_status") if postgres else sa.Enum(
        *_ENUMS["question_status"], name="question_status")
    sstatus = _enum("test_session_status") if postgres else sa.Enum(
        *_ENUMS["test_session_status"], name="test_session_status")
    outcome = _enum("answer_outcome") if postgres else sa.Enum(
        *_ENUMS["answer_outcome"], name="answer_outcome")

    # ── Vivier de questions, rattaché à l'offre ───────────────────────────────
    op.create_table(
        "test_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_offer_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("job_offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("correct_answer", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", difficulty, nullable=False, server_default="MOYENNE"),
        sa.Column("kind", kind, nullable=False, server_default="QCM_UNIQUE"),
        sa.Column("status", qstatus, nullable=False, server_default="GENEREE"),
        sa.Column("expected_seconds", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("skill_tag", sa.String(length=80), nullable=True),
        sa.Column("generated_by", sa.String(length=40), nullable=True),
        sa.Column("validated_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("times_served", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_test_questions_offer_status", "test_questions",
                    ["job_offer_id", "status"])
    op.create_index("ix_test_questions_offer_difficulty", "test_questions",
                    ["job_offer_id", "difficulty"])
    op.create_index("ix_test_questions_difficulty", "test_questions", ["difficulty"])
    op.create_index("ix_test_questions_status", "test_questions", ["status"])
    op.create_index("ix_test_questions_skill_tag", "test_questions", ["skill_tag"])

    # ── Session de passage, rattachée à la candidature ────────────────────────
    op.create_table(
        "test_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", sstatus, nullable=False, server_default="ENVOYE"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("sent_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("link_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("correct_count", sa.Integer(), nullable=True),
        sa.Column("total_overrun_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overrun_question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anomaly_flags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_test_sessions_application_id", "test_sessions", ["application_id"])
    op.create_index("ix_test_sessions_token", "test_sessions", ["token"], unique=True)
    op.create_index("ix_test_sessions_status", "test_sessions", ["status"])

    # ── Réponses ──────────────────────────────────────────────────────────────
    op.create_table(
        "test_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("test_questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("given_answer", sa.JSON(), nullable=True),
        sa.Column("outcome", outcome, nullable=False, server_default="NON_ATTEINTE"),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overrun_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_test_answers_session_id", "test_answers", ["session_id"])
    op.create_index("ix_test_answers_session_position", "test_answers",
                    ["session_id", "position"], unique=True)

    # ── Les deux autres volets, sur le score existant ─────────────────────────
    op.add_column("candidate_scores", sa.Column("test_score", sa.Float(), nullable=True))
    op.add_column("candidate_scores", sa.Column("interview_score", sa.Float(), nullable=True))
    op.add_column("candidate_scores", sa.Column("interview_notes", sa.Text(), nullable=True))
    op.add_column("candidate_scores", sa.Column("interview_ai_suggestion", sa.JSON(), nullable=True))
    op.add_column("candidate_scores", sa.Column("composite_score", sa.Float(), nullable=True))
    op.add_column("candidate_scores", sa.Column("composite_completeness", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()

    for colonne in ("composite_completeness", "composite_score", "interview_ai_suggestion",
                    "interview_notes", "interview_score", "test_score"):
        op.drop_column("candidate_scores", colonne)

    op.drop_table("test_answers")
    op.drop_table("test_sessions")
    op.drop_table("test_questions")

    if bind.dialect.name == "postgresql":
        for nom in _ENUMS:
            postgresql.ENUM(name=nom).drop(bind, checkfirst=True)
