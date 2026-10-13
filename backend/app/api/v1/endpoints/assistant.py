"""
Assistant PIQBIT : une question en langage libre, une réponse tirée des données.

  POST /assistant/message   → réponse, lignes de résultat, relances

Le droit `assistant:read` ouvre la conversation ; chaque donnée renvoyée
exige EN PLUS le droit de la page correspondante (voir le service).
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_active_user
from app.core.rbac import require
from app.db.session import get_db
from app.models.user import User
from app.schemas.assistant import (
    AssistantContexte, AssistantElement, AssistantMessage, AssistantReponse, AssistantSource,
)
from app.services.assistant_service import Contexte, assistant_service

router = APIRouter()


@router.post("/message", response_model=AssistantReponse,
             dependencies=[Depends(require("assistant", "read"))])
async def envoyer_message(
    body: AssistantMessage,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    contexte = Contexte(outil=body.contexte.outil, offre_id=body.contexte.offre_id) if body.contexte else None
    r = await assistant_service.repondre(db, body.message, current_user, contexte)
    await db.commit()  # la base de connaissances a pu mettre des vecteurs en cache
    return AssistantReponse(
        reponse=r.texte,
        elements=[AssistantElement(libelle=e.libelle, detail=e.detail, lien=e.lien, parametres=e.parametres)
                  for e in r.elements],
        suggestions=r.suggestions,
        contexte=AssistantContexte(outil=r.outil, offre_id=r.offre_id),
        sources=[AssistantSource(**{k: s.get(k) for k in ("id", "title", "category", "source", "score")})
                 for s in r.sources],
        confiance=r.confiance,
    )
