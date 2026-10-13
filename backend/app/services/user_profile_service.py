"""
Assemblage de la fiche d'un utilisateur pour l'administration.

Le point d'attention de ce module est le nombre de requêtes. Une fiche candidat
touche cinq tables — compte, dossier candidat, candidatures, offres, scores,
sessions de test. Écrit naïvement, cela donne une requête par candidature, puis
une autre par session : un candidat avec quinze candidatures ferait trente
allers-retours pour afficher une page.

Tout est donc chargé en requêtes groupées, comme l'enrichissement du classement
des candidats le fait déjà.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import application_status
from app.models.assessment import SessionStatus, TestSession
from app.models.interview import InterviewInvitation
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User

logger = logging.getLogger(__name__)


class UserProfileService:
    """Construit la fiche complète, ou la fiche de compte seule."""

    async def build(self, db: AsyncSession, user_id: UUID) -> Optional[dict]:
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if not user:
            return None

        fiche: dict = {
            "account": user,
            "is_candidate": False,
            "candidate": None,
            "applications": [],
            "stats": {"applications": 0, "tests_taken": 0,
                      "interviews": 0, "best_score": None},
        }

        candidat = (await db.execute(
            select(Candidate).where(Candidate.user_id == user_id)
        )).scalar_one_or_none()
        if not candidat:
            # Un RH ou un administrateur n'a pas de candidatures. On s'arrête
            # au compte plutôt que de rendre des sections vides, qui se
            # liraient comme une donnée manquante.
            return fiche

        fiche["is_candidate"] = True
        fiche["candidate"] = {
            "id": candidat.id,
            "full_name": candidat.full_name,
            "phone": candidat.phone,
            "cv_filename": candidat.cv_filename,
            # Sert à l'aperçu du CV — même exposition que sur les candidatures.
            "cv_path": candidat.cv_path,
            "cv_uploaded_at": candidat.cv_uploaded_at,
            "created_at": candidat.created_at,
        }

        fiche["applications"] = await self._candidatures(db, candidat.id)
        fiche["stats"] = await self._compteurs(db, candidat.id, fiche["applications"])
        return fiche

    # ── Candidatures ──────────────────────────────────────────────────────────

    async def _candidatures(self, db: AsyncSession,
                            candidate_id: UUID) -> list[dict]:
        lignes = (await db.execute(
            select(Application, JobOffer, CandidateScore)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .outerjoin(CandidateScore,
                       CandidateScore.application_id == Application.id)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.created_at.desc())
        )).all()
        if not lignes:
            return []

        # Les sessions de test en UNE requête : une par candidature donnerait
        # autant d'allers-retours que de candidatures.
        app_ids = [a.id for a, _, _ in lignes]
        sessions: dict[UUID, TestSession] = {}
        for session in (await db.execute(
            select(TestSession)
            .where(TestSession.application_id.in_(app_ids))
            .order_by(TestSession.created_at.asc())
        )).scalars().all():
            sessions[session.application_id] = session   # la dernière l'emporte

        return [
            {
                "id": app.id,
                "job_offer_id": offre.id,
                "job_title": offre.title,
                "status": app.status,
                "status_label": application_status.label(app.status),
                "applied_at": app.created_at,
                "expected_salary": app.expected_salary,
                "cv_score": score.total_score if score else None,
                "composite_score": score.composite_score if score else None,
                "composite_completeness": (score.composite_completeness
                                           if score else None),
                "interview_score": score.interview_score if score else None,
                "interview_notes": score.interview_notes if score else None,
                "interview_ai_summary": self._resume_ia(score),
                "test": self._test(sessions.get(app.id)),
            }
            for app, offre, score in lignes
        ]

    @staticmethod
    def _resume_ia(score: Optional[CandidateScore]) -> Optional[str]:
        """
        Le résumé texte de la proposition du modèle, s'il existe.

        `interview_ai_suggestion` est un objet JSON complet (critères, notes
        par critère, synthèse) ; on n'en tire ici que la phrase de synthèse,
        pour situer la note du RH sans dupliquer tout le détail — qui se
        consulte dans l'écran d'évaluation lui-même.
        """
        if not score or not score.interview_ai_suggestion:
            return None
        return score.interview_ai_suggestion.get("summary") or None

    @staticmethod
    def _test(session: Optional[TestSession]) -> Optional[dict]:
        """
        Le résumé d'un test — jamais le détail des réponses.

        Ce détail existe et se consulte, mais depuis l'écran Test technique,
        qui l'accompagne de son contexte. Le recopier ici en ferait une seconde
        source à maintenir.
        """
        if not session:
            return None
        return {
            "status": session.status.value,
            "score": session.score,
            "correct_count": session.correct_count,
            "question_count": session.question_count,
            "submitted_at": session.submitted_at,
        }

    # ── Compteurs ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _compteurs(db: AsyncSession, candidate_id: UUID,
                         candidatures: list[dict]) -> dict:
        app_ids = [c["id"] for c in candidatures]

        entretiens = 0
        if app_ids:
            entretiens = await db.scalar(
                select(func.count(InterviewInvitation.id)).where(
                    InterviewInvitation.application_id.in_(app_ids)
                )
            ) or 0

        # Un test « passé » est un test RENDU. Un lien envoyé et jamais ouvert
        # ne compte pas : le confondre gonflerait le chiffre sans rien dire du
        # candidat.
        rendus = sum(
            1 for c in candidatures
            if c["test"] and c["test"]["status"] in (SessionStatus.TERMINE.value,
                                                     SessionStatus.EXPIRE.value)
        )
        scores = [c["cv_score"] for c in candidatures if c["cv_score"] is not None]

        return {
            "applications": len(candidatures),
            "tests_taken": rendus,
            "interviews": entretiens,
            "best_score": max(scores) if scores else None,
        }


user_profile_service = UserProfileService()
