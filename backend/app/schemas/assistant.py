"""Schémas de l'assistant PIQBIT (voir `app/services/assistant_service.py`)."""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AssistantContexte(BaseModel):
    """Ce que le client rappelle de la réponse précédente, pour les relances."""
    outil: Optional[str] = Field(default=None, max_length=40)
    offre_id: Optional[UUID] = None


class AssistantMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    contexte: Optional[AssistantContexte] = None


class AssistantElement(BaseModel):
    """Une ligne de résultat, avec la page où agir (route Angular et paramètres)."""
    libelle: str
    detail: str = ""
    lien: Optional[str] = None
    parametres: dict[str, str] = {}


class AssistantSource(BaseModel):
    id: str
    title: str
    category: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None


class AssistantReponse(BaseModel):
    reponse: str
    elements: list[AssistantElement] = []
    #: Questions de relance, cliquables : chacune est comprise par l'assistant.
    suggestions: list[str] = []
    contexte: AssistantContexte
    #: Renseignées seulement quand la réponse vient de la base de connaissances.
    sources: list[AssistantSource] = []
    confiance: Optional[float] = None
