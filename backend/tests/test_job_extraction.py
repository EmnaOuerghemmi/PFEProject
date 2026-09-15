"""
Remplissage assisté du formulaire de création d'offre.

Deux garanties, et la seconde est celle qui compte le plus :

1. **Rien n'est enregistré ici.** L'endpoint propose des champs, il ne crée
   aucune offre — le RH garde la main jusqu'à l'envoi du formulaire lui-même.
2. **Rien n'est inventé.** Un champ absent du texte source doit rester absent
   de la réponse. C'est le seul rempart contre une offre qui affiche une
   exigence — « 5 ans d'expérience », un mode de travail — que personne n'a
   réellement posée.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.job_extraction_agent import job_extraction_agent as agent
from app.core.security import hash_password
from app.models.user import User, UserRole

from tests.conftest import VALID_PASSWORD

EXTRACT = "/api/v1/recruitment/jobs/extract-from-text"


async def _entete_rh(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
                role=UserRole.ADMIN, is_active=True, is_verified=True))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Nettoyage des champs — sans dépendre d'une clé LLM ─────────────────────────

def test_un_champ_hors_vocabulaire_est_ecarte():
    """
    Le formulaire rejetterait une valeur inventée ; mieux vaut l'écarter ici,
    avec un champ simplement absent plutôt qu'une erreur de validation opaque
    pour le RH.
    """
    sale = {
        "title": "Développeur Python",
        "work_mode": "FULL_REMOTE",          # hors vocabulaire
        "contract_types": ["CDI", "INTERIM"],  # INTERIM n'existe pas ici
        "required_education_level": "BAC+5",   # pas le code attendu
    }
    propre = agent._nettoyer(sale)
    assert "work_mode" not in propre
    assert propre["contract_types"] == ["CDI"]
    assert "required_education_level" not in propre


def test_une_experience_hors_bornes_est_ecartee():
    propre = agent._nettoyer({"required_experience_years": -3})
    assert "required_experience_years" not in propre
    propre2 = agent._nettoyer({"required_experience_years": 200})
    assert "required_experience_years" not in propre2


def test_une_liste_de_competences_vide_reste_absente():
    """Une liste vide et un champ absent ne doivent pas se distinguer pour le
    formulaire : les deux disent « rien à en tirer »."""
    assert "required_skills" not in agent._nettoyer({"required_skills": []})
    assert "required_skills" not in agent._nettoyer({"required_skills": None})


def test_les_competences_sont_dedupliquees_sans_perdre_lordre():
    propre = agent._nettoyer({"contract_types": ["CDI", "CDD", "CDI", "STAGE"]})
    assert propre["contract_types"] == ["CDI", "CDD", "STAGE"]


def test_un_titre_vide_ou_blanc_reste_absent():
    assert "title" not in agent._nettoyer({"title": ""})
    assert "title" not in agent._nettoyer({"title": "   "})


# ── Le parseur face à ce que les modèles renvoient vraiment ────────────────────

def test_un_objet_enrobe_dun_bloc_de_code_est_lu():
    brut = '```json\n{"title": "Développeur"}\n```'
    objet = agent._parser(brut)
    assert objet == {"title": "Développeur"}


def test_un_objet_precede_dune_phrase_est_lu():
    brut = 'Voici le résultat :\n{"title": "Développeur"}'
    assert agent._parser(brut) == {"title": "Développeur"}


def test_une_reponse_sans_json_ne_casse_rien():
    assert agent._parser("Désolé, je ne peux pas.") is None
    assert agent._parser("") is None
    assert agent._parser('["pas", "un", "objet"]') is None


def test_une_reponse_tronquee_recupere_ce_qui_est_complet():
    """
    Régression : `gemini-3.6-flash` consommait la quasi-totalité du budget de
    jetons en réflexion interne invisible, coupant la réponse en plein milieu
    de la description — le champ le plus long, donc le plus exposé. Perdre
    TOUT l'objet pour un seul champ coupé serait dommage : le titre, déjà
    complet avant la coupure, doit survivre.
    """
    tronque = (
        '{\n  "title": "Architecte Solutions Cloud Senior",\n'
        '  "description": "Nous recherchons un(e) Architecte Solutions Cloud '
        'Senior pour piloter la transformation'
    )
    objet = agent._parser(tronque)
    assert objet == {"title": "Architecte Solutions Cloud Senior"}


def test_une_accolade_dans_la_description_ne_trompe_pas_la_recuperation():
    """
    Un texte source technique peut contenir des accolades — `${var}`,
    `docker-compose.yml`. Les compter sans tenir compte des chaînes couperait
    au mauvais endroit.
    """
    tronque = (
        '{"title": "Dev", "description": "Connaît {docker-compose} et '
        "l'orchestration\", \"required_skills\": [\"Docker"
    )
    objet = agent._parser(tronque)
    assert objet["title"] == "Dev"
    assert objet["description"] == "Connaît {docker-compose} et l'orchestration"


def test_une_troncature_avant_le_premier_champ_complet_ne_casse_rien():
    """Rien à récupérer : la coupure tombe avant la première virgule sûre."""
    assert agent._parser('{"title": "Architecte Cloud Se') is None


# ── Dégradation sans clé LLM ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sans_cle_llm_le_formulaire_reste_remplissable_a_la_main():
    if agent.llm_enabled:
        pytest.skip("Une clé LLM est configurée sur cet environnement.")
    rapport = await agent.run("Développeur Python, 3 ans d'expérience.")
    assert rapport["ok"] is False
    assert "à la main" in rapport["reason"]
    assert rapport["fields"] == {}


@pytest.mark.asyncio
async def test_un_texte_trop_court_est_refuse_avant_lappel_au_modele():
    """Pas la peine de dépenser un appel pour trois mots."""
    rapport = await agent.run("Développeur")
    assert rapport["ok"] is False
    assert rapport["fields"] == {}


# ── L'endpoint ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lendpoint_est_reserve_au_rh(client: AsyncClient):
    resp = await client.post(EXTRACT, json={"text": "Développeur Python confirmé."})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_lendpoint_necree_aucune_offre(
    client: AsyncClient, db: AsyncSession
):
    """
    Le contrôle qui compte : cet endpoint est une PROPOSITION. Une offre créée
    ici court-circuiterait la relecture du RH avant publication.
    """
    from sqlalchemy import select
    from app.models.recruitment import JobOffer

    avant = len((await db.execute(select(JobOffer.id))).all())
    await client.post(EXTRACT, json={"text": "Développeur Python confirmé, 3 ans."},
                      headers=await _entete_rh(client, db))
    apres = len((await db.execute(select(JobOffer.id))).all())
    assert apres == avant


@pytest.mark.asyncio
async def test_un_texte_trop_court_est_refuse_par_lapi(
    client: AsyncClient, db: AsyncSession
):
    resp = await client.post(EXTRACT, json={"text": "x"},
                             headers=await _entete_rh(client, db))
    assert resp.status_code == 422
