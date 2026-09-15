"""
Optional Google Gemini integration.

Free-tier alternative to Claude for the same LLM-assisted features (e.g. the
negotiation chat assistant). Same contract as `claude_client.py`: works fully
without an API key (deterministic fallback), imports the `google-generativeai`
SDK lazily so the backend never hard-fails if the package isn't installed.
"""
import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self) -> None:
        self.api_key: str = settings.GEMINI_API_KEY or ""
        self.model_name: str = settings.GEMINI_MODEL or "gemini-2.0-flash"
        self._model = None  # lazily created google.generativeai.GenerativeModel instance

    @property
    def available(self) -> bool:
        """True only when both an API key and the SDK are present."""
        if not self.api_key:
            return False
        return self._ensure_model() is not None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if not self.api_key:
            return None
        try:
            import google.generativeai as genai  # lazy import — optional dependency
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        except Exception as exc:  # pragma: no cover - depends on optional dep
            logger.warning(f"Gemini SDK unavailable, Gemini features disabled: {exc}")
            self._model = None
        return self._model

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 600,
    ) -> Optional[str]:
        """
        Return Gemini's text completion, or None when the client is not
        available so callers can fall back to deterministic logic.
        """
        model = self._ensure_model()
        if model is None:
            return None
        try:
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            response = model.generate_content(
                full_prompt,
                generation_config={"max_output_tokens": max_tokens},
            )
            text = (getattr(response, "text", "") or "").strip()
            return text or None
        except Exception as exc:  # pragma: no cover - network/runtime
            logger.error(f"Gemini completion failed: {exc}")
            return None


gemini_client = GeminiClient()
