"""
Routage des modèles de langage selon la nature des données.

La garantie testée ici est celle que la plateforme annonce : une donnée
personnelle ne quitte jamais l'infrastructure. Elle doit tenir même dans le
cas le plus tentant — Claude et Gemini disponibles, Ollama absent — où un
repli « pour rendre service » la ferait sortir.

Aucun appel réseau : les fournisseurs sont remplacés par des doublures.
"""
import logging

import pytest

from app.integrations import llm_router
from app.integrations import ollama_client as module_ollama


class _Fournisseur:
    """Doublure d'un client LLM : même contrat, appels enregistrés."""

    def __init__(self, disponible: bool, texte: str = "réponse", model: str = "test"):
        self._disponible = disponible
        self.texte = texte
        self.model = model
        self.appels: list[dict] = []

    @property
    def available(self) -> bool:
        return self._disponible

    def complete(self, prompt, system=None, max_tokens=600, **options):
        self.appels.append({"prompt": prompt, **options})
        return self.texte


@pytest.fixture
def fournisseurs(monkeypatch):
    def installer(*, claude: bool, gemini: bool, ollama: bool):
        doublures = {
            "claude": _Fournisseur(claude, "via claude", "claude-test"),
            "gemini": _Fournisseur(gemini, "via gemini", "gemini-test"),
            "ollama": _Fournisseur(ollama, "via ollama", "qwen-test"),
        }
        for nom, doublure in doublures.items():
            monkeypatch.setattr(llm_router, f"{nom}_client", doublure)
        return doublures
    return installer


# ── La garantie ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_donnee_personnelle_ne_part_jamais_vers_le_cloud(fournisseurs):
    f = fournisseurs(claude=True, gemini=True, ollama=False)

    reponse = await llm_router.generer("Notes sur Mme X.", donnees_personnelles=True)

    assert reponse is None, "sans modèle local, l'appelant doit appliquer son repli"
    assert f["claude"].appels == []
    assert f["gemini"].appels == []


@pytest.mark.asyncio
async def test_une_donnee_personnelle_va_au_modele_local(fournisseurs):
    f = fournisseurs(claude=True, gemini=True, ollama=True)

    reponse = await llm_router.generer("CV de M. Y.", donnees_personnelles=True)

    assert reponse.texte == "via ollama"
    assert reponse.fournisseur == "ollama:qwen-test"
    assert f["claude"].appels == [] and f["gemini"].appels == []


@pytest.mark.asyncio
async def test_le_cloud_ne_rend_pas_disponible_un_traitement_personnel(fournisseurs):
    fournisseurs(claude=True, gemini=True, ollama=False)

    assert await llm_router.disponible(donnees_personnelles=True) is False
    assert await llm_router.disponible(donnees_personnelles=False) is True


def test_la_nature_des_donnees_doit_etre_declaree():
    """Pas de valeur par défaut : un appel qui ne déclare rien est refusé."""
    with pytest.raises(TypeError):
        llm_router.generer("texte")


# ── Données non personnelles ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_les_autres_donnees_suivent_claude_puis_gemini_puis_le_local(fournisseurs):
    fournisseurs(claude=False, gemini=True, ollama=True)
    assert (await llm_router.generer("Offre", donnees_personnelles=False)).fournisseur \
        == "gemini:gemini-test"

    fournisseurs(claude=False, gemini=False, ollama=True)
    # Hors ligne : le modèle local prend le relais.
    assert (await llm_router.generer("Offre", donnees_personnelles=False)).fournisseur \
        == "ollama:qwen-test"


@pytest.mark.asyncio
async def test_json_attendu_n_est_transmis_qu_au_modele_local(fournisseurs):
    f = fournisseurs(claude=False, gemini=True, ollama=True)
    await llm_router.generer("Offre", donnees_personnelles=False, json_attendu=True)
    assert "json_attendu" not in f["gemini"].appels[0]

    await llm_router.generer("Notes", donnees_personnelles=True, json_attendu=True)
    assert f["ollama"].appels[0]["json_attendu"] is True


@pytest.mark.asyncio
async def test_aucun_fournisseur_disponible(fournisseurs):
    fournisseurs(claude=False, gemini=False, ollama=False)
    assert await llm_router.generer("x", donnees_personnelles=False) is None


# ── Client Ollama ─────────────────────────────────────────────────────────────

class _ReponseHTTP:
    def __init__(self, donnees: dict):
        self._donnees = donnees

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._donnees


def test_le_modele_tire_sans_etiquette_est_reconnu(monkeypatch):
    """`ollama pull llama3.2` s'inscrit sous « llama3.2:latest »."""
    monkeypatch.setattr(module_ollama.httpx, "get", lambda *a, **k: _ReponseHTTP(
        {"models": [{"name": "llama3.2:latest"}]}))
    client = module_ollama.OllamaClient()
    client.model = "llama3.2"
    assert client._sonder() is True

    client.model = "qwen2.5:3b"
    assert client._sonder() is False, "un modèle non téléchargé n'est pas disponible"


def test_la_reflexion_n_est_jamais_rendue_comme_reponse(monkeypatch):
    monkeypatch.setattr(module_ollama.httpx, "post", lambda *a, **k: _ReponseHTTP(
        {"message": {"content": "<think>raisonnement interne</think>Résumé final."}}))
    assert module_ollama.OllamaClient().complete("CV") == "Résumé final."


def test_ni_le_prompt_ni_la_reponse_ne_sont_journalises(monkeypatch, caplog):
    """CLAUDE.md : jamais de données personnelles de CV dans les journaux."""
    monkeypatch.setattr(module_ollama.httpx, "post", lambda *a, **k: _ReponseHTTP({
        "message": {"content": "Mme Amira Ben Salah, 5 ans en data."},
        "eval_count": 12, "eval_duration": 2_000_000_000, "total_duration": 3_000_000_000,
    }))
    with caplog.at_level(logging.DEBUG, logger=module_ollama.logger.name):
        module_ollama.OllamaClient().complete("CV de Mme Amira Ben Salah")

    assert "Amira" not in caplog.text
    assert "12 jetons" in caplog.text, "le débit, lui, est journalisé"
