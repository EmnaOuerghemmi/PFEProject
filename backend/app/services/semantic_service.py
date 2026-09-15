"""
Matching sémantique CV ↔ offre et recherche de candidats similaires.

Indexation : chaque offre et chaque CV analysé est encodé en vecteur
(`embedding_service`) et stocké dans la table `embeddings` (JSON portable).
Sur PostgreSQL avec l'extension `vector`, une colonne `vec vector(N)` + index
HNSW sont ajoutés au boot (micro-migration dans main.py) et les recherches
passent par l'opérateur de distance cosinus `<=>` de pgvector. Sans
l'extension (SQLite en tests, PG non équipé), la similarité est calculée en
Python sur les vecteurs JSON — même résultat, juste moins scalable.

Convention d'identifiants :
- entity_type='job_offer', entity_id = job_offers.id
- entity_type='cv',        entity_id = applications.id  (CVAnalysis est
  unique par candidature, et c'est la candidature qu'on affiche côté RH)
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import Embedding
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CVAnalysis, CandidateScore
from app.services.embedding_service import (
    embedding_service, build_job_text, build_cv_text,
)

logger = logging.getLogger(__name__)


class SemanticService:
    # Positionné à True par main.py si l'extension pgvector est opérationnelle.
    pgvector_enabled: bool = False

    # ── Indexation ────────────────────────────────────────────────────────────

    async def _upsert(
        self, db: AsyncSession, *, entity_type: str, entity_id: UUID,
        vector: list[float], preview: str,
    ) -> Embedding:
        row = (
            await db.execute(
                select(Embedding).where(
                    Embedding.entity_type == entity_type,
                    Embedding.entity_id == entity_id,
                )
            )
        ).scalar_one_or_none()
        model = embedding_service.backend
        if row:
            row.model = model
            row.dim = len(vector)
            row.vector_json = vector
            row.text_preview = preview[:500]
        else:
            row = Embedding(
                entity_type=entity_type, entity_id=entity_id, model=model,
                dim=len(vector), vector_json=vector, text_preview=preview[:500],
            )
            db.add(row)
        await db.flush()

        # Peupler la colonne pgvector (SQL brut : la colonne n'existe que sur PG).
        if self.pgvector_enabled:
            try:
                vec_literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
                await db.execute(
                    text("UPDATE embeddings SET vec = CAST(:v AS vector) WHERE id = :id"),
                    {"v": vec_literal, "id": row.id},
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"pgvector column update failed: {exc}")
        return row

    async def index_job(self, db: AsyncSession, job: JobOffer) -> Embedding:
        job_text = build_job_text(job)
        vector = await embedding_service.aembed(job_text)
        return await self._upsert(
            db, entity_type="job_offer", entity_id=job.id,
            vector=vector, preview=job_text,
        )

    async def index_cv(self, db: AsyncSession, analysis: CVAnalysis) -> Embedding:
        cv_text = build_cv_text(analysis)
        vector = await embedding_service.aembed(cv_text)
        return await self._upsert(
            db, entity_type="cv", entity_id=analysis.application_id,
            vector=vector, preview=cv_text,
        )

    async def index_job_later(self, job_id) -> None:
        """
        Indexe une offre HORS du cycle requête/réponse.

        L'indexation coûte le prix d'un encodage neuronal — jusqu'à ~120 s au
        tout premier appel, le temps que le modèle se charge. La faire dans la
        route de création faisait attendre l'utilisateur tout ce temps devant un
        bouton « Créer » figé, pour un travail dont le résultat ne lui est pas
        rendu. Elle part donc en tâche de fond, avec sa PROPRE session : celle
        de la requête est refermée dès la réponse envoyée.

        Silencieuse par construction : la recherche sémantique est un confort,
        son échec ne doit jamais remonter à l'utilisateur ni casser l'offre,
        qui est déjà enregistrée à ce stade.
        """
        from app.db.session import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                job = await db.get(JobOffer, job_id)
                if job is None:
                    return
                await self.index_job(db, job)
                await db.commit()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(f"Indexation sémantique différée échouée pour {job_id}: {exc}")

    async def reindex_all(self, db: AsyncSession) -> dict:
        """Ré-indexe toutes les offres + tous les CV analysés (idempotent)."""
        jobs = (await db.execute(select(JobOffer))).scalars().all()
        for job in jobs:
            await self.index_job(db, job)
        analyses = (
            await db.execute(select(CVAnalysis).where(CVAnalysis.is_parsed.is_(True)))
        ).scalars().all()
        for analysis in analyses:
            await self.index_cv(db, analysis)
        return {"jobs_indexed": len(jobs), "cvs_indexed": len(analyses)}

    # ── Recherche ─────────────────────────────────────────────────────────────

    async def _get_embedding(
        self, db: AsyncSession, entity_type: str, entity_id: UUID
    ) -> Optional[Embedding]:
        return (
            await db.execute(
                select(Embedding).where(
                    Embedding.entity_type == entity_type,
                    Embedding.entity_id == entity_id,
                )
            )
        ).scalar_one_or_none()

    async def _rank_cvs(
        self, db: AsyncSession, query_vector: list[float], model: str,
        *, exclude_application_id: Optional[UUID] = None, limit: int = 10,
    ) -> list[tuple[UUID, float]]:
        """
        Retourne [(application_id, similarité 0..1)] triés par similarité
        décroissante — via pgvector si actif, sinon cosinus en Python.
        Seuls les vecteurs produits par le même backend sont comparés.
        """
        if self.pgvector_enabled:
            try:
                vec_literal = "[" + ",".join(f"{x:.6f}" for x in query_vector) + "]"
                sql = """
                    SELECT entity_id, 1 - (vec <=> CAST(:q AS vector)) AS sim
                    FROM embeddings
                    WHERE entity_type = 'cv' AND model = :model AND vec IS NOT NULL
                """
                params: dict = {"q": vec_literal, "model": model, "k": limit}
                if exclude_application_id is not None:
                    sql += " AND entity_id != :excl"
                    params["excl"] = exclude_application_id
                sql += " ORDER BY vec <=> CAST(:q AS vector) LIMIT :k"
                rows = (await db.execute(text(sql), params)).all()
                return [(row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
                         float(row[1])) for row in rows]
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"pgvector search failed, python fallback: {exc}")

        # Fallback Python : charge les vecteurs JSON et calcule le cosinus.
        query = select(Embedding).where(
            Embedding.entity_type == "cv", Embedding.model == model
        )
        if exclude_application_id is not None:
            query = query.where(Embedding.entity_id != exclude_application_id)
        rows = (await db.execute(query)).scalars().all()
        scored = [
            (row.entity_id, embedding_service.cosine(query_vector, row.vector_json))
            for row in rows
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:limit]

    async def _enrich(
        self, db: AsyncSession, ranked: list[tuple[UUID, float]]
    ) -> list[dict]:
        """Complète chaque (application_id, sim) avec candidat, offre, skills, score IA."""
        if not ranked:
            return []
        app_ids = [app_id for app_id, _ in ranked]
        rows = (
            await db.execute(
                select(Application, Candidate, JobOffer, CVAnalysis, CandidateScore)
                .join(Candidate, Application.candidate_id == Candidate.id)
                .join(JobOffer, Application.job_offer_id == JobOffer.id)
                .outerjoin(CVAnalysis, CVAnalysis.application_id == Application.id)
                .outerjoin(CandidateScore, CandidateScore.application_id == Application.id)
                .where(Application.id.in_(app_ids))
            )
        ).all()
        by_app = {app.id: (app, cand, job, analysis, score) for app, cand, job, analysis, score in rows}

        results = []
        for app_id, sim in ranked:
            ctx = by_app.get(app_id)
            if not ctx:
                continue
            app, cand, job, analysis, score = ctx
            results.append({
                "application_id": str(app_id),
                "candidate_id": str(cand.id),
                # Compte utilisateur : c'est LUI qu'adresse la fiche
                # back-office (/admin/users/:id), pas l'identifiant candidat.
                "user_id": str(cand.user_id) if cand.user_id else None,
                "candidate_name": cand.full_name,
                "job_offer_id": str(job.id),
                "job_title": job.title,
                "application_status": app.status,
                "semantic_score": round(max(0.0, min(1.0, sim)) * 100, 1),
                "keyword_score": score.total_score if score else None,
                "skills": (analysis.extracted_skills or [])[:12] if analysis else [],
                "experience_years": analysis.extracted_experience_years if analysis else None,
            })
        return results

    async def match_candidates_for_job(
        self, db: AsyncSession, job_id: UUID, limit: int = 10
    ) -> dict:
        """Classe les CV analysés par proximité sémantique avec l'offre."""
        job = (
            await db.execute(select(JobOffer).where(JobOffer.id == job_id))
        ).scalar_one_or_none()
        if not job:
            return {"error": "job_not_found"}

        # Indexe l'offre à la volée si absente (ou si le backend a changé).
        emb = await self._get_embedding(db, "job_offer", job_id)
        if not emb or emb.model != embedding_service.backend:
            emb = await self.index_job(db, job)

        ranked = await self._rank_cvs(db, emb.vector_json, emb.model, limit=limit)
        return {
            "job_offer_id": str(job_id),
            "job_title": job.title,
            "backend": emb.model,
            "pgvector": self.pgvector_enabled,
            "results": await self._enrich(db, ranked),
        }

    async def similar_candidates(
        self, db: AsyncSession, application_id: UUID, limit: int = 5
    ) -> dict:
        """Trouve les candidats dont le CV ressemble le plus à celui-ci (toutes offres)."""
        analysis = (
            await db.execute(
                select(CVAnalysis).where(CVAnalysis.application_id == application_id)
            )
        ).scalar_one_or_none()
        if not analysis:
            return {"error": "cv_not_analyzed"}

        emb = await self._get_embedding(db, "cv", application_id)
        if not emb or emb.model != embedding_service.backend:
            emb = await self.index_cv(db, analysis)

        ranked = await self._rank_cvs(
            db, emb.vector_json, emb.model,
            exclude_application_id=application_id, limit=limit,
        )
        return {
            "application_id": str(application_id),
            "backend": emb.model,
            "pgvector": self.pgvector_enabled,
            "results": await self._enrich(db, ranked),
        }

    async def stats(self, db: AsyncSession) -> dict:
        counts = (
            await db.execute(
                select(Embedding.entity_type, func.count(Embedding.id))
                .group_by(Embedding.entity_type)
            )
        ).all()
        by_type = {t: c for t, c in counts}
        return {
            **embedding_service.status,
            "pgvector": self.pgvector_enabled,
            "indexed_jobs": by_type.get("job_offer", 0),
            "indexed_cvs": by_type.get("cv", 0),
        }


semantic_service = SemanticService()
