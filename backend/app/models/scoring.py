import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, Index, Boolean, Integer, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import expression
from sqlalchemy.orm import relationship
from app.db.base import Base


class CVAnalysis(Base):
    __tablename__ = "cv_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False, unique=True)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    raw_text = Column(Text, nullable=True)
    extracted_skills = Column(JSON, nullable=False, default=list)
    extracted_experience_years = Column(Float, nullable=True)
    extracted_education_level = Column(String(20), nullable=True)
    extracted_job_titles = Column(JSON, nullable=False, default=list)
    extracted_keywords = Column(JSON, nullable=False, default=list)
    is_parsed = Column(Boolean, default=False, nullable=False)
    parsed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_cv_analyses_application_id", "application_id"),
        Index("ix_cv_analyses_candidate_id", "candidate_id"),
    )


class CandidateScore(Base):
    __tablename__ = "candidate_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=False, unique=True)
    job_offer_id = Column(UUID(as_uuid=True), ForeignKey("job_offers.id"), nullable=False)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    total_score = Column(Float, nullable=False)
    skills_score = Column(Float, nullable=False)
    experience_score = Column(Float, nullable=False)
    education_score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=True)
    score_details = Column(JSON, nullable=True)

    # ── Les deux autres volets de l'évaluation ────────────────────────────────
    # `total_score` reste la note du CV seul : elle a ses consommateurs et son
    # historique. Le composite des trois volets vit dans `composite_score`.
    test_score = Column(Float, nullable=True)          # recopié depuis TestSession
    interview_score = Column(Float, nullable=True)     # décision du RH
    interview_notes = Column(Text, nullable=True)      # notes libres du RH
    # Proposition du modèle, conservée À PART de la décision humaine : les
    # confondre interdirait de savoir, plus tard, si le RH a suivi la suggestion
    # — et donc de mesurer si cette suggestion vaut quelque chose.
    interview_ai_suggestion = Column(JSON, nullable=True)

    # ── Ce que le CANDIDAT a le droit de voir ─────────────────────────────
    # Décidé par le RH, candidature par candidature. Faux par défaut.
    #
    # Le détail qui compte : quand c'est faux, le candidat ne voit pas la
    # section — il ne voit pas non plus qu'elle existe. Un « votre recruteur
    # n'a pas partagé cette note » transformerait chaque candidature en
    # demande de partage, et mettrait le RH en position de se justifier.
    test_score_visible = Column(Boolean, nullable=False, default=False,
                                server_default=expression.false())
    interview_feedback_visible = Column(Boolean, nullable=False, default=False,
                                        server_default=expression.false())
    # Retour rédigé POUR le candidat, distinct de `interview_notes` qui reste
    # interne : des observations prises pour soi ne se relisent pas de la même
    # façon qu'un message adressé à quelqu'un.
    candidate_feedback = Column(Text, nullable=True)

    composite_score = Column(Float, nullable=True)
    # 1, 2 ou 3 volets disponibles. Affiché avec la note : deux candidats dont
    # la complétude diffère ne sont pas comparables.
    composite_completeness = Column(Integer, nullable=True)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_candidate_scores_application_id", "application_id"),
        Index("ix_candidate_scores_job_offer_id", "job_offer_id"),
        Index("ix_candidate_scores_candidate_id", "candidate_id"),
        Index("ix_candidate_scores_job_rank", "job_offer_id", "rank"),
    )
