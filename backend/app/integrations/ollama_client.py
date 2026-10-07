"""
Intégration Ollama : modèle de langage exécuté LOCALEMENT.

Même contrat que `claude_client.py` et `gemini_client.py` — une propriété
`available`, puis `complete()` qui rend du texte ou None — pour que le routeur
(`llm_router.py`) traite les trois fournisseurs de la même façon.

C'est à ce client, et à lui seul, que le routeur confie les prompts contenant
des données personnelles. Il ne journalise donc JAMAIS ni le prompt ni la
réponse : seulement le modèle, la durée et le débit.

Aucune dépendance nouvelle : l'API d'Ollama est du HTTP simple, et `httpx` est
déjà une dépendance du projet.
"""
import logging
import re
import threading
import time
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Durée de validité d'une sonde de disponibilité. Sans cache, chaque appel
# paierait un aller-retour HTTP de plus ; avec un cache trop long, un Ollama
# démarré après le backend resterait ignoré.
_DUREE_CACHE_SONDE = 30.0
_DELAI_SONDE = 2.0
# Un serveur local répond en quelques millisecondes. Sous Windows, un port
# fermé met en revanche ~2 s à refuser la connexion : sans cette borne, chaque
# sonde d'un Ollama absent coûtait plusieurs secondes à l'appel en cours.
_DELAI_CONNEXION_SONDE = 0.5

# Certains modèles écrivent leur réflexion dans la réponse, entre balises
# <think>…</think>, quand l'API ne la sépare pas. Ce n'est jamais la réponse.
_REFLEXION = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaClient:
    def __init__(self) -> None:
        self.base_url: str = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model: str = settings.OLLAMA_MODEL
        self._verrou = threading.Lock()
        self._sonde_valable_jusqua = 0.0
        self._disponible = False
        self._absence_signalee = False

    @property
    def available(self) -> bool:
        """
        True si le serveur Ollama répond ET que le modèle configuré est téléchargé.

        Le résultat est gardé 30 s : la propriété fait au plus un appel réseau
        par fenêtre. Depuis du code asynchrone, l'appeler via
        `asyncio.to_thread` — c'est ce que fait le routeur.
        """
        if not settings.OLLAMA_ENABLED:
            return False
        with self._verrou:
            if time.monotonic() < self._sonde_valable_jusqua:
                return self._disponible
            self._disponible = self._sonder()
            self._sonde_valable_jusqua = time.monotonic() + _DUREE_CACHE_SONDE
            return self._disponible

    def _sonder(self) -> bool:
        try:
            reponse = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=httpx.Timeout(_DELAI_SONDE, connect=_DELAI_CONNEXION_SONDE),
            )
            reponse.raise_for_status()
            noms = {modele.get("name", "") for modele in reponse.json().get("models", [])}
        except Exception as exc:
            logger.debug("Ollama injoignable (%s) : repli déterministe.", type(exc).__name__)
            return False

        # `ollama pull llama3.2` s'inscrit sous le nom « llama3.2:latest ».
        if self.model in noms or f"{self.model}:latest" in noms:
            self._absence_signalee = False
            return True
        if not self._absence_signalee:
            logger.warning(
                "Ollama répond, mais le modèle « %s » n'est pas téléchargé. "
                "Lancer : ollama pull %s", self.model, self.model,
            )
            self._absence_signalee = True
        return False

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 600,
        json_attendu: bool = False,
    ) -> Optional[str]:
        """
        Réponse du modèle local, ou None en cas d'échec : l'appelant applique
        alors sa logique déterministe.

        `json_attendu` contraint la sortie à du JSON valide — une aide précieuse
        sur un petit modèle. La consigne « réponds en JSON » doit rester dans le
        prompt : la documentation d'Ollama prévient que, sans elle, le modèle
        peut produire de longues suites d'espaces.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        charge: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {
                "num_predict": max_tokens,
                "num_ctx": settings.OLLAMA_NUM_CTX,
                # Résumé, évaluation, conseil chiffré : des tâches factuelles.
                # Une température basse stabilise aussi le JSON d'un petit modèle.
                "temperature": 0.2,
            },
        }
        if json_attendu:
            charge["format"] = "json"
        if settings.OLLAMA_DISABLE_THINKING:
            charge["think"] = False

        try:
            reponse = httpx.post(
                f"{self.base_url}/api/chat", json=charge,
                timeout=settings.OLLAMA_TIMEOUT_SECONDS,
            )
            reponse.raise_for_status()
            donnees = reponse.json()
        except httpx.TimeoutException:
            logger.warning("Ollama (%s) : pas de réponse en %.0f s.",
                           self.model, settings.OLLAMA_TIMEOUT_SECONDS)
            return None
        except Exception as exc:
            # Le type seul, jamais le message : selon l'erreur, il peut citer
            # le contenu de la requête, donc des données personnelles.
            logger.warning("Ollama (%s) : appel en échec (%s).", self.model, type(exc).__name__)
            return None

        contenu = (donnees.get("message") or {}).get("content") or ""
        texte = _REFLEXION.sub("", contenu).strip()

        jetons = donnees.get("eval_count") or 0
        generation = (donnees.get("eval_duration") or 0) / 1e9
        total = (donnees.get("total_duration") or 0) / 1e9
        logger.info(
            "Ollama (%s) : %d jetons en %.1f s (%.1f jetons/s, %.1f s au total).",
            self.model, jetons, generation, jetons / generation if generation else 0.0, total,
        )
        return texte or None


ollama_client = OllamaClient()
