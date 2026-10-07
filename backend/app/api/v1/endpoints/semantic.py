"""
Matching sémantique (embeddings + pgvector) — backoffice RH/Admin.

  GET  /semantic/status                          → backend effectif, pgvector, compteurs
  POST /semantic/reindex                         → (ré)indexe offres + CV analysés
  GET  /semantic/jobs/{job_id}/match?limit=      → candidats classés par similarité avec l'offre
  GET  /semantic/applications/{app_id}/similar   → candidats au profil similaire (toutes offres)
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.db.session import get_db
from app.services.recommendation_service import recommendation_service
from app.services.semantic_service import semantic_service

router = APIRouter(
    dependencies=[Depends(require("semantic", "read"))]
)


@router.get("/status")
async def semantic_status(db: Annotated[AsyncSession, Depends(get_db)]):
    """État du moteur sémantique : backend d'embedding, pgvector, volumes indexés."""
    return await semantic_service.stats(db)


@router.post("/reindex")
async def semantic_reindex(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    (Ré)indexe toutes les offres et tous les CV analysés. À lancer après
    l'activation du modèle d'embedding ou pour rattraper l'historique.
    """
    result = await semantic_service.reindex_all(db)
    await db.commit()
    return result


@router.get("/jobs/{job_id}/match")
async def match_candidates(
    job_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=10, ge=1, le=50),
):
    """Classement des CV analysés par **similarité sémantique** avec l'offre."""
    result = await semantic_service.match_candidates_for_job(db, job_id, limit)
    if result.get("error") == "job_not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offre introuvable")
    await db.commit()  # l'offre a pu être indexée à la volée
    return result


@router.get("/candidates/{candidate_id}/recommendations")
async def candidate_recommendations(
    candidate_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=6, ge=1, le=20),
):
    """
    Offres recommandées à un candidat — vue RH, symétrique de
    `/jobs/{job_id}/match`.

    Même moteur que la section affichée au candidat
    (`recommendation_service`), pour que le RH voie exactement ce que le
    candidat voit — un écart entre les deux rendrait l'échange impossible.

    Une liste vide n'est pas une erreur : CV pas encore analysé, ou aucune
    offre au-dessus du seuil.
    """
    offres = await recommendation_service.recommend_for_candidate(
        db, candidate_id, limit=limit)
    return {"recommendations": offres}


@router.get("/applications/{application_id}/similar")
async def similar_candidates(
    application_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=5, ge=1, le=20),
):
    """Candidats dont le profil ressemble le plus à celui-ci (sourcing interne)."""
    result = await semantic_service.similar_candidates(db, application_id, limit)
    if result.get("error") == "cv_not_analyzed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV non analysé — lancez d'abord l'analyse IA de cette candidature.",
        )
    await db.commit()
    return result
