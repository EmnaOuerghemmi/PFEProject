"""
Score composite : CV, test technique, entretien.

Une seule règle gouverne ce module, et c'est celle qui fait toute la
différence : **une note manquante n'est pas un zéro.**

Un candidat qui n'a pas encore passé l'entretien n'a pas « zéro à l'entretien ».
Si le composite traitait l'absence comme une valeur, tous les dossiers en cours
de processus s'effondreraient en bas du classement — précisément pendant la
phase où ce classement sert le plus. Le composite se calcule donc sur les
volets DISPONIBLES, renormalisés, et la complétude accompagne toujours la note.

Deux conséquences que l'appelant doit respecter :

* deux candidats dont la complétude diffère ne sont pas comparables — le
  classement les groupe, ou affiche la complétude à côté de la note ;
* la note porte une marge. Un test de douze questions a une précision de
  l'ordre de ±8 points : afficher « 74 » suggère une exactitude qui n'existe
  pas. `band()` donne la lecture honnête.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import SessionStatus, TestSession
from app.models.recruitment import JobOffer
from app.models.scoring import CandidateScore

logger = logging.getLogger(__name__)

# Pondérations par défaut des trois volets.
#
# Le CV pèse le moins parce que c'est la mesure la plus INDIRECTE : il dit ce
# que le candidat déclare. Le test dit ce qu'il sait faire, sur un périmètre
# étroit. L'entretien couvre le plus large mais reste le plus subjectif. Aucune
# des trois ne mérite de dominer.
DEFAULT_WEIGHTS = {"cv": 0.30, "test": 0.35, "interview": 0.35}

# Marge d'incertitude indicative, en points. Un test de 12 items ne permet pas
# d'affirmer que 75 vaut mieux que 70 ; il permet d'affirmer que 85 vaut mieux
# que 45.
UNCERTAINTY_POINTS = 8


class CompositeScoreService:

    def compute(
        self,
        *,
        cv_score: Optional[float],
        test_score: Optional[float],
        interview_score: Optional[float],
        weights: Optional[dict] = None,
    ) -> dict:
        """
        Compose la note finale sur les volets disponibles.

        Exemple : CV 80, test 60, entretien non passé.
        `(80×0.30 + 60×0.35) / (0.30+0.35)` = **69,2 sur 2 volets** — et non 45,
        qui serait le résultat si l'entretien manquant comptait pour zéro.
        """
        poids = {**DEFAULT_WEIGHTS, **(weights or {})}
        volets = {"cv": cv_score, "test": test_score, "interview": interview_score}
        disponibles = {k: v for k, v in volets.items() if v is not None}

        if not disponibles:
            return {
                "score": None, "completeness": 0, "available": [], "missing": list(volets),
                "band": "indisponible", "uncertainty": UNCERTAINTY_POINTS,
                "breakdown": {}, "comparable_with": 0,
            }

        somme_poids = sum(poids[k] for k in disponibles) or 1.0
        score = sum(v * poids[k] for k, v in disponibles.items()) / somme_poids

        return {
            "score": round(score, 1),
            "completeness": len(disponibles),
            "available": sorted(disponibles),
            "missing": sorted(set(volets) - set(disponibles)),
            "band": self.band(score),
            "uncertainty": UNCERTAINTY_POINTS,
            "breakdown": {
                k: {
                    "value": round(v, 1),
                    # Poids RÉEL après renormalisation : sur deux volets, le CV
                    # ne pèse plus 0.30 mais 0.46. Afficher le poids nominal
                    # laisserait croire que la note manquante a compté.
                    "weight": round(poids[k] / somme_poids, 3),
                }
                for k, v in disponibles.items()
            },
            # Un candidat noté sur 1 volet ne se compare pas à un candidat noté
            # sur 3 : l'appelant regroupe là-dessus.
            "comparable_with": len(disponibles),
        }

    @staticmethod
    def band(score: Optional[float]) -> str:
        """
        Lecture par bandes plutôt qu'au point près.

        La précision du composite ne justifie pas de distinguer 74 de 71 ;
        elle justifie de distinguer un dossier solide d'un dossier fragile.
        """
        if score is None:
            return "indisponible"
        if score >= 75:
            return "solide"
        if score >= 55:
            return "correct"
        if score >= 35:
            return "fragile"
        return "insuffisant"

    async def refresh(self, db: AsyncSession, application_id: UUID) -> Optional[CandidateScore]:
        """
        Recalcule et persiste le composite d'une candidature.

        Le volet test est repris de la DERNIÈRE session terminée : une session
        encore en cours n'a pas de note, et la reprendre reviendrait à noter un
        candidat sur un test qu'il n'a pas fini.
        """
        score = (await db.execute(
            select(CandidateScore).where(CandidateScore.application_id == application_id)
        )).scalar_one_or_none()
        if not score:
            return None

        session = (await db.execute(
            select(TestSession)
            .where(
                TestSession.application_id == application_id,
                TestSession.status.in_([SessionStatus.TERMINE, SessionStatus.EXPIRE]),
            )
            .order_by(TestSession.submitted_at.desc())
        )).scalars().first()
        if session and session.score is not None:
            score.test_score = session.score

        offre = (await db.execute(
            select(JobOffer).where(JobOffer.id == score.job_offer_id)
        )).scalar_one_or_none()

        resultat = self.compute(
            cv_score=score.total_score,
            test_score=score.test_score,
            interview_score=score.interview_score,
            weights=self._weights_for(offre),
        )
        score.composite_score = resultat["score"]
        score.composite_completeness = resultat["completeness"]
        await db.flush()
        logger.info("Composite de la candidature %s : %s sur %d volet(s).",
                    application_id, resultat["score"], resultat["completeness"])
        return score

    @staticmethod
    def _weights_for(offre: Optional[JobOffer]) -> dict:
        """
        Pondérations de l'offre si elle en porte, sinon celles par défaut.

        Le modèle `JobOffer` n'a pas encore de colonnes dédiées : on lit
        prudemment pour que l'ajout ultérieur de `weight_cv` / `weight_test` /
        `weight_interview` n'exige aucune modification ici.
        """
        if offre is None:
            return dict(DEFAULT_WEIGHTS)
        return {
            "cv": getattr(offre, "weight_cv", None) or DEFAULT_WEIGHTS["cv"],
            "test": getattr(offre, "weight_test", None) or DEFAULT_WEIGHTS["test"],
            "interview": getattr(offre, "weight_interview", None) or DEFAULT_WEIGHTS["interview"],
        }


composite_score_service = CompositeScoreService()
