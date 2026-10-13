"""
Assistant PIQBIT : n'importe quel message, une réponse juste — tirée des données.

Cas réel à l'origine du module : « bonjour » recevait la FAQ sur le délai de
réponse aux candidatures (confiance 20 %). Ce qui est vérifié ici :

* la conversation courante a sa réponse, et une question glissée après un
  « bonjour » n'est pas perdue ;
* les questions de données lisent la vraie base (offres, classement,
  candidats, entretiens…), sous les mêmes droits que les pages ;
* un message incompris reçoit un « je n'ai pas compris » et des relances,
  jamais une réponse au hasard ;
* une relance (« et pour l'offre X ? ») reprend l'outil précédent.
"""
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_status import ApplicationStatus
from app.models.interview import InterviewSlot, InvitationStatus, interview_members
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.cag_service import cag_service
from app.services.assistant_service import normaliser

from tests.test_interview_second_round import _invitation, _maintenant
from tests.test_interview_stages import _personnel

URL = "/api/v1/assistant/message"


async def _demander(client: AsyncClient, entetes: dict, message: str, contexte: dict | None = None) -> dict:
    resp = await client.post(URL, json={"message": message, "contexte": contexte}, headers=entetes)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _offre_avec_candidat(db: AsyncSession, titre: str, nom: str, *, score: float = 72,
                               statut: str = ApplicationStatus.REVIEWED.value) -> tuple[JobOffer, Application]:
    suffixe = uuid.uuid4().hex[:8]
    user = User(email=f"a_{suffixe}@example.com", username=f"a_{suffixe}", hashed_password="x",
                full_name=nom, is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name=nom)
    offre = JobOffer(title=titre, description="Poste de test.", required_skills=["Python"],
                     is_active=True, status="PUBLISHED")
    db.add_all([candidat, offre])
    await db.flush()
    candidature = Application(candidate_id=candidat.id, job_offer_id=offre.id, cv_file_path="/tmp/cv.pdf",
                              status=statut)
    db.add(candidature)
    await db.flush()
    db.add(CandidateScore(application_id=candidature.id, job_offer_id=offre.id, candidate_id=candidat.id,
                          total_score=score, skills_score=score, experience_score=score, education_score=score))
    await db.commit()
    return offre, candidature


# ── Conversation ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bonjour_recoit_une_salutation_et_non_une_faq(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    r = await _demander(client, entetes, "bonjour")

    assert r["reponse"].startswith("Bonjour")
    assert "48 heures" not in r["reponse"]
    assert r["suggestions"], "des relances cliquables sont proposées"
    assert r["sources"] == []


@pytest.mark.asyncio
async def test_une_question_apres_bonjour_n_est_pas_perdue(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    await _offre_avec_candidat(db, "Analyste Cybersécurité", "Lina Haddad")

    r = await _demander(client, entetes, "Bonjour, combien d'offres publiées ?")

    assert r["reponse"].startswith("Bonjour")
    assert "offre(s) publiée(s)" in r["reponse"]
    assert any(e["libelle"] == "Analyste Cybersécurité" for e in r["elements"])


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["xqzt plorb", "quelle est la capitale du Pérou ?", "🙂"])
async def test_un_message_incompris_le_dit_au_lieu_de_repondre_au_hasard(
    client: AsyncClient, db: AsyncSession, message: str,
):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    await cag_service.seed_default_kb(db)
    await db.commit()

    r = await _demander(client, entetes, message)

    assert r["reponse"].startswith("Je n'ai pas compris")
    assert r["suggestions"]


@pytest.mark.asyncio
async def test_l_aide_decrit_ce_que_sait_faire_l_assistant(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RECRUTEUR)
    r = await _demander(client, entetes, "Que sais-tu faire ?")
    assert "données de PIQBIT" in r["reponse"]
    # Le recruteur n'a pas accès aux contrats : on ne les lui promet pas.
    assert "contrats" not in r["reponse"]


# ── Données ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classement_demande_l_offre_puis_la_retrouve_par_son_titre(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    offre, candidature = await _offre_avec_candidat(db, "Ingénieur Data Pipeline", "Yasmine Belhadj", score=88)

    sans_offre = await _demander(client, entetes, "Qui sont les meilleurs candidats ?")
    assert sans_offre["reponse"].startswith("Pour quelle offre")
    assert "Meilleurs candidats pour Ingénieur Data Pipeline" in sans_offre["suggestions"]

    r = await _demander(client, entetes, "Meilleurs candidats pour ingenieur data pipeline")
    assert "Classement pour « Ingénieur Data Pipeline »" in r["reponse"]
    assert r["elements"][0]["libelle"] == "#1 Yasmine Belhadj"
    assert r["elements"][0]["lien"] == "/admin/decision"
    assert r["elements"][0]["parametres"] == {"offre": str(offre.id), "candidature": str(candidature.id)}
    assert r["contexte"]["outil"] == "classement"


@pytest.mark.asyncio
async def test_une_relance_reprend_l_outil_precedent(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    await _offre_avec_candidat(db, "Comptable Senior", "Karim Jaziri")

    r = await _demander(client, entetes, "et pour comptable senior ?", contexte={"outil": "classement"})

    assert r["contexte"]["outil"] == "classement"
    assert "Classement pour « Comptable Senior »" in r["reponse"]


@pytest.mark.asyncio
async def test_un_candidat_cite_par_son_nom_ouvre_sa_fiche(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RECRUTEUR)
    await _offre_avec_candidat(db, "Designer Produit", "Nour Mansouri", statut=ApplicationStatus.ON_HOLD.value)

    r = await _demander(client, entetes, "Où en est Nour Mansouri ?")

    assert r["contexte"]["outil"] == "candidat"
    assert r["reponse"] == "Nour Mansouri : 1 candidature(s)."
    assert r["elements"][0]["libelle"] == "Designer Produit"
    assert "En réserve" in r["elements"][0]["detail"]


@pytest.mark.asyncio
async def test_candidats_en_reserve(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    await _offre_avec_candidat(db, "Chef de Projet IT", "Sami Gharbi", statut=ApplicationStatus.ON_HOLD.value)

    r = await _demander(client, entetes, "Quels candidats sont en réserve ?")

    assert r["contexte"]["outil"] == "reserve"
    assert [e["libelle"] for e in r["elements"]] == ["Sami Gharbi"]


@pytest.mark.asyncio
async def test_les_droits_du_role_s_appliquent(client: AsyncClient, db: AsyncSession):
    """Le recruteur n'a pas accès aux contrats : l'assistant non plus, et ne les lui suggère pas."""
    entetes, _ = await _personnel(client, db, UserRole.RECRUTEUR)

    r = await _demander(client, entetes, "Contrats en attente de signature")

    assert "n'est pas accessible avec votre rôle (Recruteur)" in r["reponse"]
    assert not any("ontrat" in s for s in r["suggestions"])


@pytest.mark.asyncio
async def test_un_candidat_n_a_pas_acces_a_l_assistant(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.CANDIDAT)
    resp = await client.post(URL, json={"message": "bonjour"}, headers=entetes)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_un_recruteur_ne_voit_que_ses_entretiens(client: AsyncClient, db: AsyncSession):
    rh, _ = await _personnel(client, db, UserRole.RH)
    recruteur, recruteur_id = await _personnel(client, db, UserRole.RECRUTEUR)
    _, candidature = await _offre_avec_candidat(db, "Testeur QA", "Amel Trabelsi",
                                                statut=ApplicationStatus.INTERVIEW_SCHEDULED.value)
    invitation = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                                   debut=_maintenant() + timedelta(days=2))
    creneau = (await db.execute(
        select(InterviewSlot).where(InterviewSlot.invitation_id == invitation.id))).scalar_one()
    invitation.confirmed_slot_id = creneau.id
    await db.commit()

    vu_par_rh = await _demander(client, rh, "Entretiens à venir")
    assert [e["libelle"] for e in vu_par_rh["elements"]] == ["Amel Trabelsi"]
    assert "heure de" in vu_par_rh["elements"][0]["detail"]

    assert (await _demander(client, recruteur, "Entretiens à venir"))["elements"] == []

    await db.execute(interview_members.insert().values(invitation_id=invitation.id, user_id=recruteur_id))
    await db.commit()
    db.expire(invitation, ["membres"])  # session partagée avec l'API : membres relus
    assert [e["libelle"] for e in (await _demander(client, recruteur, "Entretiens à venir"))["elements"]] \
        == ["Amel Trabelsi"]


# ── Mode d'emploi ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_question_comment_repond_par_le_guide(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    await cag_service.seed_default_kb(db)
    await cag_service.index_knowledge(db)
    await db.commit()

    r = await _demander(client, entetes, "Comment planifier un entretien ?")

    assert r["contexte"]["outil"] == "connaissances"
    assert "Planifier un entretien" in r["reponse"]
    assert r["sources"][0]["title"] == "Comment planifier un entretien ?"


def test_normaliser():
    assert normaliser("Entretiens à venir ?") == "entretiens a venir"
    assert normaliser("  Où  en est  Nour-Mansouri ") == "ou en est nour mansouri"
