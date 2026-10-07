"""
CAG (Cache-Augmented Generation) — assistant extractif hors-ligne, sans LLM.

  GET    /cag/status                         → backend, volumes, mode
  POST   /cag/reindex                        → (ré)embed la base de connaissances (cache)
  POST   /cag/seed                           → insère la FAQ de démo (idempotent)
  POST   /cag/ask                            → question → réponse extractive sourcée (auth)
  POST   /cag/cv/{application_id}/ask        → question sur un CV (RH/Admin)
  GET    /cag/knowledge                      → liste des entrées (RH/Admin)
  POST   /cag/knowledge                      → ajoute une entrée (RH/Admin)
  DELETE /cag/knowledge/{id}                 → supprime une entrée (RH/Admin)
"""
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.services.cag_service import cag_service

router = APIRouter()

_RH = require("assistant", "write")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class KnowledgeCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=10)
    category: str = Field(default="AUTRE", max_length=40)
    source: str | None = Field(default=None, max_length=200)


# ── Statut / indexation ───────────────────────────────────────────────────────

@router.get("/status")
async def cag_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """
    État du moteur CAG, traçage compris.

    `tracing.content_traced` est exposé délibérément : c'est la seule façon de
    vérifier depuis l'extérieur qu'aucun contenu de CV ne sort vers le traceur.
    Un réglage de confidentialité qu'on ne peut pas constater ne rassure
    personne.
    """
    from app.observability.langfuse_client import langfuse_client

    stats = await cag_service.stats(db)
    stats["tracing"] = langfuse_client.status
    return stats


@router.post("/reindex", dependencies=[Depends(_RH)])
async def cag_reindex(db: Annotated[AsyncSession, Depends(get_db)]):
    """(Ré)embed la base de connaissances — à lancer après changement de backend."""
    count = await cag_service.index_knowledge(db)
    await db.commit()
    return {"reindexed": count}


@router.post("/seed", dependencies=[Depends(_RH)])
async def cag_seed(db: Annotated[AsyncSession, Depends(get_db)]):
    """Insère la FAQ de démonstration (idempotent)."""
    created = await cag_service.seed_default_kb(db)
    await cag_service.index_knowledge(db)
    await db.commit()
    return {"created": created}


# ── Assistant (base de connaissances) ─────────────────────────────────────────

@router.post("/ask")
async def cag_ask(
    body: AskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Réponse extractive sourcée depuis la base de connaissances (tout utilisateur authentifié)."""
    result = await cag_service.ask(
        db, body.question,
        user_id=str(current_user.id),
        # Session dérivée (utilisateur + jour) : le produit n'a pas de notion
        # de conversation, chaque question étant indépendante. Ce regroupement
        # reste utile au diagnostic — voir dix questions d'affilée dont la
        # troisième échoue en dit plus que dix traces isolées.
        session_id=f"{current_user.id}:{date.today().isoformat()}",
    )
    await db.commit()  # d'éventuels vecteurs manquants ont pu être calculés/cachés
    return result


# ── Q&A sur un CV ─────────────────────────────────────────────────────────────

@router.post("/cv/{application_id}/ask", dependencies=[Depends(_RH)])
async def cag_ask_cv(
    application_id: UUID,
    body: AskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Question sur un CV : renvoie le passage exact le plus pertinent (extraction)."""
    result = await cag_service.ask_cv(
        db, application_id, body.question,
        user_id=str(current_user.id),
        # Séance de consultation d'UNE candidature : regroupe les questions
        # successives posées sur le même dossier.
        session_id=f"{current_user.id}:{application_id}",
    )
    if result.get("error") == "application_not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidature introuvable")
    if result.get("error") == "cv_not_analyzed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CV non analysé — lancez d'abord l'analyse IA de cette candidature.",
        )
    await db.commit()
    return result


# ── CRUD base de connaissances ────────────────────────────────────────────────

@router.get("/knowledge", dependencies=[Depends(_RH)])
async def list_knowledge(db: Annotated[AsyncSession, Depends(get_db)]):
    entries = await cag_service.list_knowledge(db)
    return [
        {"id": str(e.id), "title": e.title, "content": e.content,
         "category": e.category, "source": e.source,
         "indexed": bool(e.vector_json)}
        for e in entries
    ]


@router.post("/knowledge", status_code=status.HTTP_201_CREATED, dependencies=[Depends(_RH)])
async def add_knowledge(body: KnowledgeCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    entry = await cag_service.add_knowledge(
        db, title=body.title, content=body.content, category=body.category, source=body.source,
    )
    await db.commit()
    return {"id": str(entry.id), "title": entry.title}


@router.delete("/knowledge/{entry_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(_RH)])
async def delete_knowledge(entry_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    ok = await cag_service.delete_knowledge(db, entry_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrée introuvable")
    await db.commit()
