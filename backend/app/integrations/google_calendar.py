"""
Intégration Google Calendar (optionnelle) pour la gestion des entretiens.

Authentification par **compte de service** (service account) Google Cloud :
- `GOOGLE_CALENDAR_CREDENTIALS_FILE` : chemin du JSON de clé du compte de service ;
- `GOOGLE_CALENDAR_ID` : agenda cible (id `xxx@group.calendar.google.com`
  partagé avec le compte de service, ou `primary` avec délégation domaine) ;
- `GOOGLE_CALENDAR_IMPERSONATE` (optionnel) : utilisateur Workspace à
  impersonner (domain-wide delegation).

Comme toutes les intégrations PIQBIT : **jamais bloquant**. Sans credentials,
`available` vaut False et les appels retournent None — le flux entretien
(emails + ICS) continue de fonctionner normalement.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarClient:
    """Client minimal (REST v3) pour créer/supprimer des événements d'entretien."""

    def __init__(self) -> None:
        self._credentials = None
        self._init_error: Optional[str] = None
        self._load_credentials()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _load_credentials(self) -> None:
        if not settings.GOOGLE_CALENDAR_CREDENTIALS_FILE or not settings.GOOGLE_CALENDAR_ID:
            self._init_error = "GOOGLE_CALENDAR_CREDENTIALS_FILE / GOOGLE_CALENDAR_ID non configurés"
            return
        try:
            # Import lazy : google-auth n'est requis que si la sync est activée.
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_CALENDAR_CREDENTIALS_FILE, scopes=SCOPES
            )
            if settings.GOOGLE_CALENDAR_IMPERSONATE:
                creds = creds.with_subject(settings.GOOGLE_CALENDAR_IMPERSONATE)
            self._credentials = creds
            logger.info("Google Calendar sync enabled (calendar=%s)", settings.GOOGLE_CALENDAR_ID)
        except Exception as exc:  # pragma: no cover - depends on local files
            self._init_error = str(exc)
            logger.warning("Google Calendar disabled: %s", exc)

    @property
    def available(self) -> bool:
        return self._credentials is not None

    @property
    def status(self) -> dict:
        return {
            "configured": self.available,
            "calendar_id": settings.GOOGLE_CALENDAR_ID if self.available else None,
            "impersonate": settings.GOOGLE_CALENDAR_IMPERSONATE or None,
            "reason": None if self.available else self._init_error,
        }

    def _token(self) -> Optional[str]:
        """Access token du compte de service (refresh si expiré)."""
        try:
            from google.auth.transport.requests import Request

            if not self._credentials.valid:
                self._credentials.refresh(Request())
            return self._credentials.token
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Google Calendar token refresh failed: %s", exc)
            return None

    # ── Événements ───────────────────────────────────────────────────────────

    def create_interview_event(
        self,
        *,
        summary: str,
        description: str,
        start_at: datetime,
        end_at: datetime,
        attendee_email: Optional[str] = None,
        location: str = "Visioconférence",
        with_meet: bool = True,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Crée l'événement d'entretien dans l'agenda configuré.

        Retourne `(event_id, meet_url)` :
          - `event_id` : identifiant Google de l'événement, ou None si l'appel
            a échoué (best-effort — ne lève jamais) ;
          - `meet_url` : lien Google Meet rattaché à l'événement, ou None. Google
            ne génère la conférence que si le compte de service agit au nom d'un
            utilisateur Workspace (délégation domaine). Sans cela `hangoutLink`
            est absent : l'appelant retombe alors sur Jitsi.
        """
        if not self.available:
            return None, None
        token = self._token()
        if not token:
            return None, None

        def _fmt(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()

        body: dict = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": _fmt(start_at), "timeZone": settings.GOOGLE_CALENDAR_TIMEZONE},
            "end": {"dateTime": _fmt(end_at), "timeZone": settings.GOOGLE_CALENDAR_TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 30},
                ],
            },
        }
        # L'ajout d'invités par un compte de service exige la délégation
        # domaine ; sans elle on l'omet pour ne pas faire échouer la création.
        if attendee_email and settings.GOOGLE_CALENDAR_IMPERSONATE:
            body["attendees"] = [{"email": attendee_email}]

        # Demande de conférence Meet : Google génère un `hangoutLink` à la
        # création. Ignoré silencieusement sans délégation domaine.
        params: dict = {}
        if with_meet:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            params["conferenceDataVersion"] = 1

        try:
            resp = httpx.post(
                f"{API_BASE}/calendars/{settings.GOOGLE_CALENDAR_ID}/events",
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            event_id = data.get("id")
            meet_url = data.get("hangoutLink") or self._extract_meet_uri(data)
            logger.info("Google Calendar event created: %s (meet=%s)", event_id, bool(meet_url))
            return event_id, meet_url
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Google Calendar event creation failed: %s", exc)
            return None, None

    @staticmethod
    def _extract_meet_uri(event: dict) -> Optional[str]:
        """Point d'entrée vidéo de `conferenceData`, quand `hangoutLink` manque."""
        for entry in (event.get("conferenceData") or {}).get("entryPoints", []):
            if entry.get("entryPointType") == "video" and entry.get("uri"):
                return entry["uri"]
        return None

    def delete_event(self, event_id: str) -> bool:
        """Supprime un événement (annulation d'entretien). Best-effort."""
        if not self.available or not event_id:
            return False
        token = self._token()
        if not token:
            return False
        try:
            resp = httpx.delete(
                f"{API_BASE}/calendars/{settings.GOOGLE_CALENDAR_ID}/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            # 410 = déjà supprimé : considéré comme un succès.
            if resp.status_code not in (200, 204, 410):
                resp.raise_for_status()
            logger.info("Google Calendar event deleted: %s", event_id)
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Google Calendar event deletion failed: %s", exc)
            return False


google_calendar_client = GoogleCalendarClient()
