"""
Traçage Langfuse (optionnel) du pipeline de recherche.

Comme toutes les dépendances externes de PIQBIT : **jamais bloquant**. Sans
clés, sans paquet installé, ou en cas d'erreur réseau, `available` vaut False
et chaque appel devient un no-op silencieux. Un traceur qui casse la production
est pire que pas de traceur.

VERSION DU SDK. Écrit pour **Langfuse 4.x**, dont l'interface diffère
totalement de la 2.x que montrent la plupart des tutoriels : il n'existe plus
de `client.trace(...)`. La 4.x est bâtie sur OpenTelemetry et n'expose que
`start_as_current_observation(...)`, où la trace est simplement l'observation
racine. Les observations sont typées, et deux types tombent juste ici :
`embedding` pour l'encodage de la question, `retriever` pour la récupération
des passages — ce qui donne des traces lisibles sans configuration.

CE QUI EST TRACÉ. Le pipeline CAG est extractif : **aucun appel à un modèle de
langage** sur ce chemin. Langfuse sert donc de traceur de récupération, pas de
traceur de prompts. Les observables utiles sont :

  - durée de l'encodage de la question, et backend employé ;
  - taille du corpus, nombre de passages récupérés ;
  - score de confiance du meilleur passage, et distribution des suivants ;
  - service depuis le cache ou non ;
  - refus pour confiance insuffisante.

CE QUI N'EST PAS TRACÉ. Le contenu, sauf autorisation explicite. Voir
`app/observability/redaction.py` — le défaut fermé y est justifié.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Types d'observation Langfuse employés. `span` est le repli générique.
TYPE_EMBEDDING = "embedding"
TYPE_RETRIEVER = "retriever"
TYPE_SPAN = "span"


class LangfuseClient:
    """Client minimal. N'expose que ce dont les services ont besoin."""

    def __init__(self) -> None:
        self._client: Any = None
        self._init_error: Optional[str] = None
        self._charger()

    # ── Initialisation ──────────────────────────────────────────────────────

    def _charger(self) -> None:
        if not settings.LANGFUSE_ENABLED:
            self._init_error = "LANGFUSE_ENABLED est à false"
            return
        secret = (
            settings.LANGFUSE_SECRET_KEY.get_secret_value()
            if settings.LANGFUSE_SECRET_KEY
            else ""
        )
        if not settings.LANGFUSE_PUBLIC_KEY or not secret:
            self._init_error = "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY non configurés"
            return
        try:
            # Import paresseux : `langfuse` n'est requis que si le traçage est
            # activé. Le backend doit démarrer sans le paquet.
            from langfuse import Langfuse

            from app.observability.redaction import filet_de_securite

            self._client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=secret,
                host=settings.langfuse_url,
                # Étiquette portée par chaque trace : sans elle, les traces du
                # poste de développement se mêlent à celles d'un déploiement.
                environment=settings.LANGFUSE_ENVIRONMENT,
                sample_rate=settings.LANGFUSE_SAMPLE_RATE,
                # Masque de dernier recours, appliqué par le SDK à TOUT ce
                # qu'il envoie. Les sites d'appel masquent déjà, mais cela
                # relève de la discipline ; ce filet, lui, ne dépend d'aucune
                # vigilance. Voir `redaction.filet_de_securite`.
                mask=filet_de_securite,
            )
            logger.info(
                "Traçage Langfuse actif (host=%s, contenu=%s)",
                settings.langfuse_url,
                "tracé" if settings.LANGFUSE_TRACE_CONTENT else "MASQUÉ",
            )
            if settings.LANGFUSE_TRACE_CONTENT:
                logger.warning(
                    "LANGFUSE_TRACE_CONTENT est ACTIF : le contenu des CV et des "
                    "questions sortira vers %s. À n'employer que sur une instance "
                    "auto-hébergée, avec accord et rétention définie.",
                    settings.langfuse_url,
                )
        except ImportError:
            self._init_error = "paquet `langfuse` non installé"
            logger.info("Traçage Langfuse indisponible : %s", self._init_error)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement
            self._init_error = str(exc)
            logger.warning("Traçage Langfuse désactivé : %s", exc)

    # ── État ────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def status(self) -> dict[str, Any]:
        """État de l'intégration, exposé par l'API d'administration."""
        return {
            "enabled": settings.LANGFUSE_ENABLED,
            "configured": self.available,
            "host": settings.langfuse_url if self.available else None,
            "content_traced": settings.LANGFUSE_TRACE_CONTENT,
            "sdk_major": 4,
            "reason": None if self.available else self._init_error,
        }

    # ── Traçage ─────────────────────────────────────────────────────────────

    @contextmanager
    def trace(
        self,
        nom: str,
        *,
        entree: Any = None,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator["_Trace"]:
        """
        Ouvre une trace (observation racine).

        Renvoie toujours un objet utilisable : quand le traçage est
        indisponible, c'est un objet inerte. L'appelant n'a donc jamais à
        écrire `if langfuse.available`, ce qui éviterait d'oublier le test à un
        endroit et d'y provoquer une exception.

        `entree` est l'entrée de la trace, DÉJÀ MASQUÉE par l'appelant. Elle
        compte : l'observation racine est celle qu'un relecteur ouvre en
        premier, et une trace sans entrée l'oblige à descendre dans les étapes
        pour comprendre ce qui a été demandé.

        `user_id` et `session_id` sont attendus déjà pseudonymisés — voir
        `redaction.masquer_identifiant`.

        La durée est mesurée ici et non par le SDK : elle reste juste même
        lorsque l'envoi échoue.
        """
        enveloppe = _Trace()
        debut = time.perf_counter()
        gestionnaire = None
        attributs = None
        try:
            if self.available:
                try:
                    # `propagate_attributes` est le mécanisme v4 pour les
                    # attributs de trace. Il doit ENVELOPPER la création du
                    # span racine : posé après coup, il ne se propagerait pas
                    # aux étapes filles.
                    from langfuse import propagate_attributes

                    attributs = propagate_attributes(
                        user_id=user_id, session_id=session_id, tags=tags,
                    )
                    attributs.__enter__()
                    gestionnaire = self._client.start_as_current_observation(
                        name=nom, as_type=TYPE_SPAN,
                        input=entree, metadata=metadata or {},
                    )
                    enveloppe._handle = gestionnaire.__enter__()
                except Exception as exc:  # pragma: no cover - réseau / SDK
                    logger.debug("Ouverture de trace Langfuse ignorée : %s", exc)
                    gestionnaire = None
            yield enveloppe
        except Exception:
            enveloppe.echec()
            raise
        finally:
            enveloppe._terminer(round((time.perf_counter() - debut) * 1000, 2))
            # Fermeture en ordre inverse de l'ouverture.
            for contexte in (gestionnaire, attributs):
                if contexte is None:
                    continue
                try:
                    contexte.__exit__(None, None, None)
                except Exception as exc:  # pragma: no cover
                    logger.debug("Fermeture de contexte Langfuse ignorée : %s", exc)

    def flush(self) -> None:
        """Vide la file d'envoi. À appeler à l'arrêt du service."""
        if not self.available:
            return
        try:
            self._client.flush()
        except Exception as exc:  # pragma: no cover - réseau
            logger.debug("Vidage Langfuse ignoré : %s", exc)

    def shutdown(self) -> None:
        """Arrêt propre : vide la file puis ferme le client."""
        if not self.available:
            return
        try:
            self._client.shutdown()
        except Exception as exc:  # pragma: no cover - réseau
            logger.debug("Arrêt Langfuse ignoré : %s", exc)


class _Trace:
    """
    Trace en cours. Inerte lorsque le traçage est indisponible : toutes ses
    méthodes restent appelables et ne font rien.
    """

    def __init__(self) -> None:
        self._handle: Any = None
        self._statut = "ok"
        self._sortie: dict[str, Any] = {}

    @contextmanager
    def span(
        self,
        nom: str,
        *,
        type_: str = TYPE_SPAN,
        entree: Any = None,
        modele: str | None = None,
        **metadata: Any,
    ) -> Iterator["_Span"]:
        """
        Étape interne de la trace.

        `type_` accepte les types d'observation Langfuse — employer
        `TYPE_EMBEDDING` pour un encodage et `TYPE_RETRIEVER` pour une
        récupération : l'interface les distingue visuellement, et les
        agrégations par type deviennent possibles sans travail supplémentaire.

        `modele` renseigne le champ `model` de l'observation. Sur un encodage,
        c'est le backend d'embedding — et c'est la variable qui pèse le plus
        sur la qualité de ce système : un repli non sémantique et un modèle de
        plongement ne donnent pas les mêmes résultats. La renseigner permet de
        filtrer et de comparer, plutôt que d'avoir à s'en souvenir.
        """
        etape = _Span()
        debut = time.perf_counter()
        gestionnaire = None
        try:
            if self._handle is not None:
                try:
                    kwargs: dict[str, Any] = {}
                    if modele is not None:
                        kwargs["model"] = modele
                    gestionnaire = self._handle.start_as_current_observation(
                        name=nom, as_type=type_, input=entree,
                        metadata=metadata, **kwargs,
                    )
                    etape._handle = gestionnaire.__enter__()
                except Exception as exc:  # pragma: no cover
                    logger.debug("Ouverture de span Langfuse ignorée : %s", exc)
                    gestionnaire = None
            yield etape
        except Exception:
            etape._statut = "error"
            raise
        finally:
            etape._duree_ms = round((time.perf_counter() - debut) * 1000, 2)
            if etape._handle is not None:
                try:
                    etape._handle.update(
                        output={
                            **etape._sortie,
                            "duration_ms": etape._duree_ms,
                            "status": etape._statut,
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    logger.debug("Mise à jour de span Langfuse ignorée : %s", exc)
            if gestionnaire is not None:
                try:
                    gestionnaire.__exit__(None, None, None)
                except Exception as exc:  # pragma: no cover
                    logger.debug("Fermeture de span Langfuse ignorée : %s", exc)

    def sortie(self, **valeurs: Any) -> None:
        """Enregistre le résultat de la trace (déjà masqué par l'appelant)."""
        self._sortie.update(valeurs)

    def score(
        self, nom: str, valeur: float | None, commentaire: str | None = None
    ) -> None:
        """
        Attache une mesure numérique à la trace — confiance de récupération,
        note Ragas. C'est ce qui rend une trace exploitable dans le temps :
        une durée dit si c'est lent, un score dit si c'est bon.

        Une valeur `None` est IGNORÉE, et ce n'est pas une tolérance de
        confort : certaines mesures sont légitimement sans objet — l'ancrage
        d'un refus, par exemple, puisque rien n'est extrait. Envoyer `None`
        faisait rejeter la requête par le SDK (`ScoreBody` exige un nombre) et
        perdait le score. Ne pas l'envoyer du tout est la bonne réponse : un
        score sans valeur n'est pas un score.
        """
        if self._handle is None or valeur is None:
            return
        try:
            self._handle.score_trace(name=nom, value=valeur, comment=commentaire)
        except Exception as exc:  # pragma: no cover
            logger.debug("Score Langfuse ignoré : %s", exc)

    def echec(self) -> None:
        self._statut = "error"

    def _terminer(self, duree_ms: float) -> None:
        if self._handle is None:
            return
        try:
            self._handle.update(
                output={**self._sortie, "duration_ms": duree_ms, "status": self._statut}
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("Fin de trace Langfuse ignorée : %s", exc)


class _Span:
    """Étape d'une trace. Inerte lorsque le traçage est indisponible."""

    def __init__(self) -> None:
        self._handle: Any = None
        self._statut = "ok"
        self._duree_ms = 0.0
        self._sortie: dict[str, Any] = {}

    def sortie(self, **valeurs: Any) -> None:
        self._sortie.update(valeurs)

    @property
    def duree_ms(self) -> float:
        return self._duree_ms


langfuse_client = LangfuseClient()
