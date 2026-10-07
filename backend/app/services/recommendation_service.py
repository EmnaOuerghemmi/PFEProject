"""
Recommandation d'offres à un candidat — matching INVERSE (candidat → offres).

Le sens direct (offre → candidats) vit dans `semantic_service` et sert le
back-office ; il n'est pas touché ici. Ce module assemble le sens inverse en
réutilisant les deux moteurs déjà en place plutôt qu'en réécrivant l'un ou
l'autre :

    CV analysé (CVAnalysis)
      ↓  embedding déjà indexé (semantic_service / embedding_service)
    recherche vectorielle pgvector — Top N offres candidates
      ↓
    contraintes métier bloquantes (expérience, formation)
      ↓
    reranking cross-encoder      ← optionnel, désactivé par défaut
      ↓
    score de compatibilité explicable (scoring_service + pondération de l'offre)
      ↓
    filtrage par seuil configurable
      ↓
    recommandations

Trois partis pris structurent le tout :

1. **La sémantique situe, elle ne décide pas.** Un CV de développeur Python
   « ressemble » à une offre PHP : même métier, même vocabulaire. Seules les
   compétences, l'expérience et la formation disent si la candidature tient.
   La similarité ne pèse donc qu'une minorité du score final
   (`RECOMMENDATION_SEMANTIC_WEIGHT`).

2. **Certains écarts ne se rattrapent pas.** Une offre qui exige trois ans
   d'expérience n'est pas « un peu moins compatible » pour qui en a un : elle
   est hors de portée. Ces critères sont des contraintes, pas des points de
   score — les traiter autrement ferait remonter des offres inatteignables au
   prétexte d'un bon score sémantique.

3. **Rien plutôt que du bruit.** En dessous du seuil, la liste revient vide et
   la section disparaît de l'écran. Une recommandation que le candidat juge
   absurde coûte plus cher que pas de recommandation du tout.

Aucun encodage ni chargement de modèle n'est déclenché dans le chemin de
requête : on ne lit que ce que le pipeline a déjà indexé (`scoring_agent`
pour les CV, la création d'offre pour les offres). Le premier chargement du
modèle coûte jusqu'à deux minutes — inacceptable dans une page candidat.
"""
import asyncio
import logging
import math
import threading
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.recruitment import Application, JobOffer
from app.models.scoring import CVAnalysis
from app.services.embedding_service import build_cv_text, build_job_text
from app.services.scoring_service import scoring_service, EDUCATION_LEVELS
from app.services.semantic_service import semantic_service

logger = logging.getLogger(__name__)


class RecommendationService:
    """Assemble retrieval sémantique + règles métier en recommandations."""

    def __init__(self) -> None:
        self._reranker = None
        self._reranker_failed = False
        self._lock = threading.Lock()

    # ── Reranking (optionnel) ─────────────────────────────────────────────────

    def _load_reranker(self):
        """
        Charge le cross-encoder une seule fois, si et seulement si il est
        explicitement activé.

        `CrossEncoder` vient de `sentence-transformers`, déjà installé pour les
        embeddings : activer le reranking n'ajoute aucune dépendance. Le POIDS,
        lui, est bien réel (~2,3 Go pour `bge-reranker-v2-m3`) — d'où le
        drapeau par défaut à False, et l'échec silencieux : un reranker
        indisponible dégrade le classement, il ne casse pas la page.
        """
        if not settings.RERANKER_ENABLED or self._reranker_failed:
            return None
        if self._reranker is not None:
            return self._reranker
        with self._lock:
            if self._reranker is not None or self._reranker_failed:
                return self._reranker
            try:
                from sentence_transformers import CrossEncoder
                logger.info(f"Chargement du reranker {settings.RERANKER_MODEL_NAME}…")
                self._reranker = CrossEncoder(settings.RERANKER_MODEL_NAME)
            except Exception as exc:
                self._reranker_failed = True
                logger.warning(f"Reranker indisponible, classement vectoriel conservé : {exc}")
            return self._reranker

    async def _rerank(
        self, cv_text: str, offres: list[tuple[JobOffer, float]],
    ) -> Optional[dict[UUID, float]]:
        """
        Re-note les paires (CV, offre) avec le cross-encoder.

        Renvoie `None` quand le reranking n'a pas eu lieu — l'appelant garde
        alors le cosinus. Le calcul part dans un thread : c'est du CPU pur, il
        bloquerait la boucle d'évènements.
        """
        modele = self._load_reranker()
        if modele is None or not offres:
            return None
        try:
            paires = [(cv_text, build_job_text(job)) for job, _ in offres]
            brut = await asyncio.to_thread(modele.predict, paires)
            # Les logits d'un cross-encoder ne sont pas bornés : on les ramène
            # sur 0..1 pour rester comparable au cosinus qu'ils remplacent.
            return {
                job.id: 1.0 / (1.0 + math.exp(-float(score)))
                for (job, _), score in zip(offres, brut)
            }
        except Exception as exc:
            logger.warning(f"Reranking échoué, classement vectoriel conservé : {exc}")
            return None

    # ── Contraintes métier ────────────────────────────────────────────────────

    @staticmethod
    def _contraintes_bloquantes(job: JobOffer, analysis: CVAnalysis) -> list[str]:
        """
        Motifs d'exclusion d'une offre. Liste vide ⇒ l'offre reste éligible.

        Une donnée ABSENTE n'exclut jamais : un CV dont l'expérience n'a pas pu
        être extraite n'est pas un CV sans expérience. Exclure sur une lecture
        ratée punirait le candidat pour une limite de l'outil — on préfère
        laisser l'offre passer et laisser le score dire le reste.
        """
        motifs: list[str] = []

        requis_ans = job.required_experience_years
        detecte_ans = analysis.extracted_experience_years
        if requis_ans and detecte_ans is not None and detecte_ans < requis_ans:
            motifs.append(
                f"expérience insuffisante ({detecte_ans:g} an(s) détectée(s) "
                f"pour {requis_ans:g} demandée(s))"
            )

        rang_requis = EDUCATION_LEVELS.get((job.required_education_level or "NONE").upper(), 0)
        rang_detecte = EDUCATION_LEVELS.get((analysis.extracted_education_level or "NONE").upper(), 0)
        if rang_requis and rang_detecte and rang_detecte < rang_requis:
            motifs.append(
                f"niveau d'études inférieur au niveau demandé "
                f"({job.required_education_level})"
            )

        return motifs

    # ── Explications ──────────────────────────────────────────────────────────

    @staticmethod
    def _raisons(
        job: JobOffer, analysis: CVAnalysis,
        retrouvees: list[str], manquantes: list[str], semantique: float,
    ) -> list[str]:
        """Pourquoi cette offre remonte — en clair, pas en pourcentages."""
        raisons: list[str] = []

        total_competences = len(retrouvees) + len(manquantes)
        if retrouvees:
            raisons.append(
                f"{len(retrouvees)} des {total_competences} compétences "
                f"demandées figurent dans votre CV"
            )
        elif not total_competences:
            raisons.append("Aucune compétence spécifique exigée par l'offre")

        requis_ans = job.required_experience_years
        detecte_ans = analysis.extracted_experience_years
        if requis_ans and detecte_ans is not None and detecte_ans >= requis_ans:
            raisons.append(
                f"Expérience suffisante ({detecte_ans:g} an(s) pour "
                f"{requis_ans:g} demandée(s))"
            )
        elif not requis_ans:
            raisons.append("Aucune ancienneté minimale exigée")

        if job.required_education_level:
            rang_requis = EDUCATION_LEVELS.get(job.required_education_level.upper(), 0)
            rang_detecte = EDUCATION_LEVELS.get(
                (analysis.extracted_education_level or "NONE").upper(), 0)
            if rang_detecte and rang_detecte >= rang_requis:
                raisons.append("Niveau d'études compatible")

        if semantique >= 0.5:
            raisons.append("Profil globalement proche de cette offre")

        # Ce que le CV n'a pas permis de mesurer est dit, pas masqué : le
        # critère a été écarté du calcul, le candidat doit savoir lequel —
        # c'est aussi ce qui lui indique quoi préciser dans son CV.
        if requis_ans and detecte_ans is None:
            raisons.append(
                "Expérience non détectée dans votre CV — critère non pris en compte")
        if job.required_education_level and not analysis.extracted_education_level:
            raisons.append(
                "Formation non détectée dans votre CV — critère non pris en compte")

        return raisons

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def _cv_analyse_du_candidat(
        self, db: AsyncSession, candidate_id: UUID,
    ) -> Optional[CVAnalysis]:
        """
        La lecture de CV la plus récente du candidat.

        Les analyses sont attachées à une CANDIDATURE (une par dossier), mais
        la recommandation, elle, parle du profil. On prend donc la dernière :
        c'est le CV que le candidat a déposé en dernier, donc le plus proche
        de ce qu'il est aujourd'hui.
        """
        return (await db.execute(
            select(CVAnalysis)
            .where(CVAnalysis.candidate_id == candidate_id,
                   CVAnalysis.is_parsed.is_(True))
            .order_by(CVAnalysis.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()

    async def _offres_eligibles(
        self, db: AsyncSession, candidate_id: UUID,
    ) -> list[UUID]:
        """Offres ouvertes auxquelles le candidat n'a pas déjà postulé."""
        deja_postulees = set((await db.execute(
            select(Application.job_offer_id)
            .where(Application.candidate_id == candidate_id)
        )).scalars().all())

        ouvertes = (await db.execute(
            select(JobOffer.id).where(
                JobOffer.is_active.is_(True),
                JobOffer.status == "PUBLISHED",
                (JobOffer.expires_at.is_(None)) | (JobOffer.expires_at >= func.now()),
            )
        )).scalars().all()
        return [jid for jid in ouvertes if jid not in deja_postulees]

    async def recommend_for_candidate(
        self, db: AsyncSession, candidate_id: UUID, *, limit: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Offres recommandées à ce candidat, les plus compatibles d'abord.

        Renvoie une liste vide — jamais une erreur — quand le candidat n'a pas
        de CV analysé, que rien n'est indexé, ou qu'aucune offre n'atteint le
        seuil. C'est un cas nominal, pas une panne.
        """
        analysis = await self._cv_analyse_du_candidat(db, candidate_id)
        if analysis is None:
            return []

        eligibles = await self._offres_eligibles(db, candidate_id)
        if not eligibles:
            return []

        pool = await semantic_service.search_jobs_for_cv(
            db, analysis.application_id,
            eligible_ids=eligibles, limit=settings.RECOMMENDATION_POOL_SIZE,
        )
        if not pool:
            return []

        # Une seule requête pour tout le vivier : recharger offre par offre
        # coûterait N allers-retours pour un gain nul.
        offres = {j.id: j for j in (await db.execute(
            select(JobOffer).where(JobOffer.id.in_([jid for jid, _ in pool]))
        )).scalars().all()}

        # Contraintes AVANT reranking : inutile de faire travailler un
        # cross-encoder sur des offres déjà hors de portée.
        retenues: list[tuple[JobOffer, float]] = []
        for job_id, similarite in pool:
            job = offres.get(job_id)
            if job is None or self._contraintes_bloquantes(job, analysis):
                continue
            retenues.append((job, similarite))
        if not retenues:
            return []

        scores_rerank = await self._rerank(build_cv_text(analysis), retenues)

        resultats: list[dict[str, Any]] = []
        for job, similarite in retenues:
            pertinence = (scores_rerank or {}).get(job.id, similarite)
            pertinence = max(0.0, min(1.0, pertinence))

            retrouvees, manquantes = scoring_service.compare_skills(
                job.required_skills, analysis.extracted_skills)
            note_competences = scoring_service.compute_skills_score(
                job.required_skills, analysis.extracted_skills or [])
            note_experience = scoring_service.compute_experience_score(
                job.required_experience_years, analysis.extracted_experience_years)
            note_formation = scoring_service.compute_education_score(
                job.required_education_level, analysis.extracted_education_level or "")

            # Pondération de l'OFFRE, pas une constante maison : c'est déjà la
            # règle métier appliquée au score de candidature, et deux barèmes
            # différents pour le même couple CV/offre seraient incohérents.
            #
            # Seule adaptation propre à la recommandation : un critère que le
            # CV ne permet PAS de mesurer sort du calcul (poids à zéro, les
            # autres se renormalisent) au lieu de valoir zéro. Noter zéro une
            # donnée absente est défendable pour un score de candidature — un
            # recruteur lit le CV derrière — mais ici cela retirerait
            # silencieusement des offres au candidat pour un échec de lecture
            # de l'outil. Les barèmes de `scoring_service` restent intacts.
            poids_experience = job.weight_experience
            poids_formation = job.weight_education
            if job.required_experience_years and analysis.extracted_experience_years is None:
                poids_experience = 0.0
            if job.required_education_level and not analysis.extracted_education_level:
                poids_formation = 0.0

            note_metier = scoring_service.compute_total_score(
                note_competences, note_experience, note_formation,
                job.weight_skills, poids_experience, poids_formation,
            ) / 100.0

            poids_semantique = settings.RECOMMENDATION_SEMANTIC_WEIGHT
            compatibilite = (1 - poids_semantique) * note_metier + poids_semantique * pertinence

            if compatibilite < settings.RECOMMENDATION_THRESHOLD:
                continue

            resultats.append({
                "job_id": job.id,
                "title": job.title,
                "compatibility_score": round(compatibilite, 4),
                "matching_skills": retrouvees,
                "missing_skills": manquantes,
                "reasons": self._raisons(job, analysis, retrouvees, manquantes, pertinence),
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "work_mode": job.work_mode,
                "contract_types": list(job.contract_types or []),
            })

        resultats.sort(key=lambda r: r["compatibility_score"], reverse=True)
        return resultats[:limit]


recommendation_service = RecommendationService()
