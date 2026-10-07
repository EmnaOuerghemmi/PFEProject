"""
Routage des appels aux modèles de langage selon la nature des données.

UNE règle, appliquée ici et nulle part ailleurs :

* **Données personnelles** — texte d'un CV, notes d'entretien, négociation
  avec un candidat nommé — : modèle LOCAL (Ollama), et lui seul. S'il est
  indisponible, la réponse est None et l'appelant applique sa logique
  déterministe. Il n'y a PAS de repli vers un service cloud : un repli « pour
  rendre service » suffirait à faire sortir ces données, et la garantie ne
  vaudrait plus rien.
* **Autres données** — offres d'emploi, indicateurs agrégés — : Claude, puis
  Gemini, puis Ollama en dernier recours. La plateforme garde ainsi un modèle
  même hors ligne.

`donnees_personnelles` est un argument OBLIGATOIRE, sans valeur par défaut :
impossible d'appeler un modèle sans avoir déclaré ce qu'on lui envoie. Un
défaut, quel qu'il soit, serait un oubli silencieux qui attend son heure.

Les SDK sont synchrones ; chaque appel s'exécute dans un thread. Sur
processeur, Ollama met plusieurs dizaines de secondes à répondre : appelé
directement depuis du code `async`, il figerait toute l'API pendant ce temps.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.integrations.claude_client import claude_client
from app.integrations.gemini_client import gemini_client
from app.integrations.ollama_client import ollama_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReponseLLM:
    texte: str
    # Fournisseur et modèle qui ont réellement répondu, ex. « ollama:qwen2.5:3b ».
    # À consigner tel quel : un libellé deviné après coup finit toujours faux.
    fournisseur: str


def _chaine(donnees_personnelles: bool) -> list[tuple[str, object]]:
    """Fournisseurs autorisés, dans l'ordre où ils sont essayés."""
    if donnees_personnelles:
        return [("ollama", ollama_client)]
    return [("claude", claude_client), ("gemini", gemini_client), ("ollama", ollama_client)]


def _modele(client: object) -> str:
    return getattr(client, "model", None) or getattr(client, "model_name", None) or "?"


async def _disponible(client: object) -> bool:
    try:
        return bool(await asyncio.to_thread(lambda: client.available))
    except Exception as exc:  # pragma: no cover - dépend du fournisseur
        logger.warning("Disponibilité indéterminable (%s) : fournisseur ignoré.",
                       type(exc).__name__)
        return False


async def disponible(*, donnees_personnelles: bool) -> bool:
    """True si au moins un fournisseur AUTORISÉ pour ces données répond."""
    for _, client in _chaine(donnees_personnelles):
        if await _disponible(client):
            return True
    return False


async def generer(
    prompt: str,
    *,
    donnees_personnelles: bool,
    system: Optional[str] = None,
    max_tokens: int = 600,
    json_attendu: bool = False,
) -> Optional[ReponseLLM]:
    """
    Première réponse non vide parmi les fournisseurs autorisés, ou None.

    `json_attendu` n'est transmis qu'à Ollama, seul client qui sait contraindre
    sa sortie ; pour les autres, la consigne JSON du prompt fait foi.
    """
    for nom, client in _chaine(donnees_personnelles):
        if not await _disponible(client):
            continue
        arguments: dict = {"prompt": prompt, "system": system, "max_tokens": max_tokens}
        if nom == "ollama":
            arguments["json_attendu"] = json_attendu
        try:
            texte = await asyncio.to_thread(client.complete, **arguments)
        except Exception as exc:  # pragma: no cover - les clients rattrapent déjà
            logger.warning("Fournisseur %s en échec (%s).", nom, type(exc).__name__)
            continue
        if texte:
            return ReponseLLM(texte=texte, fournisseur=f"{nom}:{_modele(client)}")
    return None
