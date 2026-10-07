"""
Création d'espaces Google Meet par l'API Meet REST v2.

POURQUOI CE MODULE EXISTE À CÔTÉ DE `google_calendar.py`. Les deux parlent à
Google, mais pas de la même façon et pas pour la même chose :

  - `google_calendar.py` emploie un **compte de service**. Il écrit dans un
    agenda partagé. Il ne peut PAS créer de Meet : Google ne délivre de
    conférence que si le compte agit au nom d'un utilisateur, ce qui exige la
    délégation domaine (donc Google Workspace).

  - Ce module emploie des **identifiants utilisateur** (OAuth). L'API Meet crée
    un espace « au nom de » la personne qui a autorisé l'application. Elle
    fonctionne avec un compte Google ordinaire, sans Workspace.

CE QUE ÇA CHANGE. `POST /v2/spaces` avec un corps vide rend immédiatement un
lien Meet, **sans événement Calendar, donc sans date**. C'est exactement ce
qu'il faut pour générer un lien au moment de la planification, avant que le
candidat n'ait choisi son créneau.

PORTÉE DEMANDÉE. `meetings.space.created` — volontairement la plus étroite :
elle ne donne accès qu'aux espaces créés par ce jeton, et à rien d'autre du
compte Google. Ni l'agenda, ni les contacts, ni les fichiers.

PRÉREQUIS CÔTÉ GOOGLE, à faire une fois dans la console Cloud :
  1. activer l'API « Google Meet » sur le projet ;
  2. ajouter la portée `.../auth/meetings.space.created` à l'écran de consentement ;
  3. déclarer l'URI de redirection de `GOOGLE_MEET_REDIRECT_URI`.
Sans ces trois points, l'autorisation échoue avec une erreur de Google, pas
de PIQBIT.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SPACES_URL = "https://meet.googleapis.com/v2/spaces"

#: Portée minimale : uniquement les espaces créés par ce jeton.
SCOPE = "https://www.googleapis.com/auth/meetings.space.created"


class GoogleMeetClient:
    """Client OAuth + API Meet. Ne lève jamais : renvoie None en cas d'échec."""

    @property
    def configured(self) -> bool:
        """Un client OAuth est déclaré. Ne dit rien de l'autorisation d'un utilisateur."""
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "redirect_uri": settings.GOOGLE_MEET_REDIRECT_URI if self.configured else None,
            "scope": SCOPE,
            "reason": None if self.configured
            else "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET non configurés",
        }

    # ── Autorisation ────────────────────────────────────────────────────────

    def url_autorisation(self, state: str) -> Optional[str]:
        """
        URL vers laquelle envoyer l'utilisateur pour qu'il autorise PIQBIT.

        `access_type=offline` et `prompt=consent` sont indispensables : sans
        eux, Google ne délivre PAS de jeton de rafraîchissement, et
        l'autorisation expirerait au bout d'une heure sans moyen de la
        renouveler. C'est l'erreur classique de ce flux.
        """
        if not self.configured:
            return None
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_MEET_REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def echanger_code(self, code: str) -> Optional[str]:
        """
        Échange le code d'autorisation contre un jeton de rafraîchissement.

        Seul le jeton de RAFRAÎCHISSEMENT est conservé : le jeton d'accès vit
        une heure et se redemande à la volée. Stocker un jeton d'accès
        obligerait à gérer son expiration partout.
        """
        if not self.configured:
            return None
        try:
            reponse = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_MEET_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                timeout=20,
            )
            reponse.raise_for_status()
            jeton = reponse.json().get("refresh_token")
            if not jeton:
                # Google omet le refresh_token quand l'utilisateur a déjà
                # autorisé l'application et que `prompt=consent` manque.
                logger.warning(
                    "Google n'a pas délivré de jeton de rafraîchissement. "
                    "Vérifier access_type=offline et prompt=consent."
                )
            return jeton
        except Exception as exc:  # pragma: no cover - réseau
            logger.warning("Échange du code Google échoué : %s", exc)
            return None

    def _jeton_acces(self, refresh_token: str) -> Optional[str]:
        """Jeton d'accès frais, obtenu depuis le jeton de rafraîchissement."""
        try:
            reponse = httpx.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
                timeout=20,
            )
            reponse.raise_for_status()
            return reponse.json().get("access_token")
        except Exception as exc:  # pragma: no cover - réseau
            logger.warning("Rafraîchissement du jeton Google échoué : %s", exc)
            return None

    # ── Création d'espace ───────────────────────────────────────────────────

    def creer_espace(self, refresh_token: str) -> dict[str, Any]:
        """
        Crée un espace Meet et renvoie son lien.

        Bloquant (httpx synchrone) : à appeler depuis un fil, jamais
        directement depuis une coroutine — voir `asyncio.to_thread` chez
        l'appelant.

        Renvoie `{"meet_url": ..., "provider": "google-meet"}` en cas de
        succès, ou `{"meet_url": None, "error": ...}` sinon. Le message
        d'erreur de Google est repris tel quel : il distingue une API non
        activée d'une portée manquante, et c'est exactement ce que l'opérateur
        a besoin de savoir.
        """
        jeton = self._jeton_acces(refresh_token)
        if not jeton:
            return {"meet_url": None,
                    "error": "Autorisation Google expirée ou révoquée. "
                             "Reconnectez le compte Google."}
        try:
            reponse = httpx.post(
                SPACES_URL,
                json={},
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=20,
            )
            if reponse.status_code >= 400:
                detail = reponse.json().get("error", {}).get("message", reponse.text)
                logger.warning("Création d'espace Meet refusée (%s) : %s",
                               reponse.status_code, detail)
                return {"meet_url": None, "error": f"Google : {detail}"}
            donnees = reponse.json()
            lien = donnees.get("meetingUri")
            if not lien:
                return {"meet_url": None,
                        "error": "Google n'a pas renvoyé de lien de réunion."}
            return {
                "meet_url": lien,
                "provider": "google-meet",
                "meeting_code": donnees.get("meetingCode"),
                "space_name": donnees.get("name"),
            }
        except Exception as exc:  # pragma: no cover - réseau
            logger.warning("Création d'espace Meet échouée : %s", exc)
            return {"meet_url": None, "error": str(exc)}


google_meet_client = GoogleMeetClient()
