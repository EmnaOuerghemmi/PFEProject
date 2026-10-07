"""
Tests du client Langfuse.

Ce que ces tests garantissent, dans l'ordre d'importance :

  1. **Le traçage ne casse jamais l'application.** Sans clés, sans paquet, ou
     avec un SDK qui lève à chaque appel, le code appelant doit continuer à
     fonctionner. C'est la propriété la plus importante : une régression ici
     transformerait un outil de diagnostic en panne de production.
  2. L'objet renvoyé est toujours utilisable, même inerte — l'appelant n'a
     jamais à tester la disponibilité.
  3. Les exceptions métier traversent la trace sans être avalées.
"""
import pytest

from app.core.config import settings
from app.observability.langfuse_client import LangfuseClient


@pytest.fixture
def client_inactif(monkeypatch):
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", False)
    return LangfuseClient()


# ── Client inactif : tout reste appelable ───────────────────────────────────

def test_client_inactif_sans_cles(client_inactif):
    assert client_inactif.available is False
    assert client_inactif.status["configured"] is False
    assert "LANGFUSE_ENABLED" in client_inactif.status["reason"]


def test_trace_utilisable_meme_inactive(client_inactif):
    """L'appelant n'a pas à écrire `if langfuse.available` : il l'oublierait."""
    with client_inactif.trace("test") as trace:
        trace.sortie(outcome="ok")
        trace.score("confiance", 0.9)
        with trace.span("etape", type_="retriever", meta=1) as etape:
            etape.sortie(count=3)
        assert etape.duree_ms >= 0


def test_flush_et_shutdown_sans_effet_si_inactif(client_inactif):
    client_inactif.flush()
    client_inactif.shutdown()


def test_score_none_nest_pas_envoye(client_inactif):
    """
    Régression. Certaines mesures sont légitimement sans objet — l'ancrage
    d'un refus, puisque rien n'est extrait. Envoyer `None` faisait rejeter la
    requête par le SDK (`ScoreBody` exige un nombre) et perdait le score.
    """
    envoyes = []

    class _SpanQuiEnregistre:
        def score_trace(self, **kwargs):
            envoyes.append(kwargs["name"])

        def update(self, **_):
            pass

    trace = _Trace_de_test(_SpanQuiEnregistre())
    trace.score("ancrage", None)
    trace.score("confiance", 0.9)
    assert envoyes == ["confiance"]


def _Trace_de_test(handle):
    from app.observability.langfuse_client import _Trace

    t = _Trace()
    t._handle = handle
    return t


def test_activation_exige_des_cles(monkeypatch):
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", True)
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", None)
    client = LangfuseClient()
    assert client.available is False
    assert "non configurés" in client.status["reason"]


# ── Exceptions : la trace ne doit rien avaler ───────────────────────────────

def test_exception_metier_traverse_la_trace(client_inactif):
    with pytest.raises(ValueError, match="panne métier"):
        with client_inactif.trace("test") as trace:
            trace.sortie(outcome="ok")
            raise ValueError("panne métier")


def test_exception_dans_un_span_traverse(client_inactif):
    with pytest.raises(KeyError):
        with client_inactif.trace("test") as trace:
            with trace.span("etape"):
                raise KeyError("absent")


# ── SDK défaillant : le traçage se dégrade, l'appelant continue ─────────────

class _SDKQuiLeve:
    """SDK dont chaque méthode échoue. Cas d'un Langfuse injoignable."""

    def start_as_current_observation(self, **_):
        raise RuntimeError("serveur Langfuse injoignable")

    def flush(self):
        raise RuntimeError("injoignable")

    def shutdown(self):
        raise RuntimeError("injoignable")


def test_sdk_defaillant_ne_casse_pas_l_appelant(client_inactif):
    """
    Le scénario redouté : Langfuse est configuré mais tombe. Le code métier
    doit s'exécuter entièrement et rendre son résultat.
    """
    client_inactif._client = _SDKQuiLeve()
    assert client_inactif.available is True

    execute = []
    with client_inactif.trace("test") as trace:
        execute.append("debut")
        with trace.span("etape") as etape:
            execute.append("milieu")
            etape.sortie(count=1)
        trace.score("confiance", 0.5)
        trace.sortie(outcome="ok")
        execute.append("fin")

    assert execute == ["debut", "milieu", "fin"]
    client_inactif.flush()
    client_inactif.shutdown()


class _SpanQuiLeve:
    def update(self, **_):
        raise RuntimeError("mise à jour impossible")

    def score_trace(self, **_):
        raise RuntimeError("score impossible")

    def start_as_current_observation(self, **_):
        raise RuntimeError("span impossible")


class _GestionnaireOK:
    def __init__(self, span):
        self._span = span

    def __enter__(self):
        return self._span

    def __exit__(self, *_):
        return False


class _SDKPartiel:
    """Le SDK ouvre la trace, mais toute écriture ultérieure échoue."""

    def start_as_current_observation(self, **_):
        return _GestionnaireOK(_SpanQuiLeve())


def test_ecritures_defaillantes_ne_cassent_pas_l_appelant(client_inactif):
    client_inactif._client = _SDKPartiel()
    execute = []
    with client_inactif.trace("test") as trace:
        with trace.span("etape") as etape:
            etape.sortie(count=1)
            execute.append("span")
        trace.score("confiance", 0.5)
        trace.sortie(outcome="ok")
        execute.append("trace")
    assert execute == ["span", "trace"]


# ── État exposé ─────────────────────────────────────────────────────────────

def test_status_annonce_le_masquage(monkeypatch, client_inactif):
    monkeypatch.setattr(settings, "LANGFUSE_TRACE_CONTENT", False)
    assert client_inactif.status["content_traced"] is False
    monkeypatch.setattr(settings, "LANGFUSE_TRACE_CONTENT", True)
    assert client_inactif.status["content_traced"] is True
