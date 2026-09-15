"""
Service d'embeddings de texte pour le matching sémantique.

Deux backends, sélectionnés par `EMBEDDINGS_BACKEND` :

- **model** : `sentence-transformers` (par défaut
  `paraphrase-multilingual-MiniLM-L12-v2`, 384 dims, multilingue FR/EN,
  tourne sur CPU). Chargé paresseusement au premier appel — l'import et le
  téléchargement du modèle ne bloquent jamais le boot de l'API.

- **hash** : repli déterministe hors-ligne ("hashing trick" sur les tokens et
  bigrammes de mots, vecteur L2-normalisé de même dimension). Qualité
  sémantique moindre (similarité lexicale, pas conceptuelle) mais suffisante
  pour les tests et pour garder la feature fonctionnelle sans le modèle —
  fidèle à la philosophie PIQBIT « aucun composant IA n'est bloquant ».

`auto` (défaut) essaie le modèle puis retombe sur hash. Les vecteurs des deux
backends ne sont pas comparables entre eux : chaque embedding stocke le nom de
son backend et les recherches ne comparent que des vecteurs du même modèle.
"""
import asyncio
import hashlib
import logging
import math
import os
import re
import threading
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

HASH_BACKEND_NAME = "hash-v1"

_TOKEN_RE = re.compile(r"[a-zà-öø-ÿ0-9+#.]{2,}", re.IGNORECASE)


class EmbeddingService:
    def __init__(self) -> None:
        self._model = None
        self._model_failed = False
        self._lock = threading.Lock()

    # ── Sélection du backend ──────────────────────────────────────────────────

    def _try_load_model(self):
        """Charge sentence-transformers une seule fois (thread-safe)."""
        if self._model is not None or self._model_failed:
            return self._model
        with self._lock:
            if self._model is not None or self._model_failed:
                return self._model
            try:
                # `huggingface_hub` lit son jeton dans l'environnement du
                # processus. Le `.env` n'est interprété que par
                # pydantic-settings : sans cet export, un HF_TOKEN configuré
                # resterait sans effet. On n'écrase jamais une variable déjà
                # posée par l'orchestrateur (Docker, CI), qui fait autorité.
                if settings.HF_TOKEN and not os.environ.get("HF_TOKEN"):
                    os.environ["HF_TOKEN"] = settings.HF_TOKEN.get_secret_value()

                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model {settings.EMBEDDING_MODEL_NAME}…")
                self._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
                logger.info("Embedding model loaded.")
            except Exception as exc:
                self._model_failed = True
                logger.warning(f"sentence-transformers unavailable → hash fallback ({exc})")
        return self._model

    @property
    def backend(self) -> str:
        """Nom effectif du backend (= identifiant de compatibilité des vecteurs)."""
        mode = settings.EMBEDDINGS_BACKEND.lower()
        if mode == "hash":
            return HASH_BACKEND_NAME
        if mode in ("model", "auto"):
            if self._try_load_model() is not None:
                return settings.EMBEDDING_MODEL_NAME
            if mode == "model":
                # Demandé explicitement mais indisponible : on le dit.
                return HASH_BACKEND_NAME
        return HASH_BACKEND_NAME

    @property
    def dim(self) -> int:
        return settings.EMBEDDING_DIM

    @property
    def status(self) -> dict:
        return {
            "requested_backend": settings.EMBEDDINGS_BACKEND,
            "effective_backend": self.backend,
            "model_loaded": self._model is not None,
            "dim": self.dim,
        }

    # ── Encodage ──────────────────────────────────────────────────────────────

    def embed(self, text: str) -> List[float]:
        """Encode un texte en vecteur L2-normalisé de `dim` dimensions."""
        text = (text or "").strip()
        if not text:
            return [0.0] * self.dim

        if self.backend != HASH_BACKEND_NAME:
            model = self._try_load_model()
            if model is not None:
                vec = model.encode(text, normalize_embeddings=True)
                return [float(x) for x in vec]

        return self._hash_embed(text)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Encodage par lot (le modèle batch nativement, le hash boucle)."""
        if self.backend != HASH_BACKEND_NAME:
            model = self._try_load_model()
            if model is not None:
                cleaned = [(t or "").strip() or " " for t in texts]
                vecs = model.encode(cleaned, normalize_embeddings=True)
                return [[float(x) for x in v] for v in vecs]
        return [self._hash_embed(t) for t in texts]

    # ── Variantes asynchrones ─────────────────────────────────────────────────

    async def aembed(self, text: str) -> List[float]:
        """
        Variante non bloquante de `embed`.

        `model.encode` est un calcul CPU synchrone : appelé tel quel depuis une
        coroutine, il fige la boucle d'événements — et donc TOUTE l'API — le
        temps de l'encodage. Le premier appel est le pire cas : il déclenche le
        chargement du modèle (~120 s mesurées, téléchargement compris).
        `to_thread` le sort du fil de la boucle.
        """
        return await asyncio.to_thread(self.embed, text)

    async def aembed_many(self, texts: List[str]) -> List[List[float]]:
        """Variante non bloquante de `embed_many` (cf. `aembed`)."""
        return await asyncio.to_thread(self.embed_many, texts)

    # ── Fallback hash ─────────────────────────────────────────────────────────

    def _hash_embed(self, text: str) -> List[float]:
        """
        Hashing trick : chaque token (et bigramme de mots) est projeté sur une
        dimension par hash stable ; le signe est dérivé du hash pour limiter
        les collisions destructives (comme HashingVectorizer). L2-normalisé.
        """
        dim = self.dim
        vec = [0.0] * dim
        tokens = _TOKEN_RE.findall(text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feat in features:
            h = int.from_bytes(hashlib.md5(feat.encode()).digest()[:8], "big")
            idx = h % dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    # ── Similarité ────────────────────────────────────────────────────────────

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        """Similarité cosinus de deux vecteurs (déjà normalisés → produit scalaire)."""
        if not a or not b or len(a) != len(b):
            return 0.0
        return float(sum(x * y for x, y in zip(a, b)))


# ── Constructeurs de texte (une seule source de vérité indexation/recherche) ──

def build_job_text(job) -> str:
    """Texte représentatif d'une offre pour l'embedding."""
    skills = ", ".join(str(s) for s in (job.required_skills or []))
    parts = [
        f"Poste : {job.title}",
        f"Compétences requises : {skills}" if skills else "",
        f"Expérience requise : {job.required_experience_years} ans"
        if job.required_experience_years is not None else "",
        (job.description or "")[:1500],
    ]
    return "\n".join(p for p in parts if p)


def build_cv_text(analysis) -> str:
    """Texte représentatif d'un CV analysé pour l'embedding."""
    skills = ", ".join(str(s) for s in (analysis.extracted_skills or []))
    titles = ", ".join(str(t) for t in (analysis.extracted_job_titles or []))
    keywords = ", ".join(str(k) for k in (analysis.extracted_keywords or [])[:30])
    parts = [
        f"Intitulés de postes : {titles}" if titles else "",
        f"Compétences : {skills}" if skills else "",
        f"Expérience : {analysis.extracted_experience_years} ans"
        if analysis.extracted_experience_years is not None else "",
        f"Formation : {analysis.extracted_education_level}"
        if analysis.extracted_education_level else "",
        f"Mots-clés : {keywords}" if keywords else "",
        (analysis.raw_text or "")[:1500],
    ]
    return "\n".join(p for p in parts if p)


embedding_service = EmbeddingService()
