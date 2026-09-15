"""
Lot 0 — le vocabulaire des statuts de candidature.

Avant ce lot, quatre déclarations concurrentes se contredisaient. Deux d'entre
elles causaient des défauts observables, et ce sont eux que ces tests fixent :

1. **La liste analytique ignorait `TEST_SENT` et `HIRED`.** La somme des statuts
   du tableau de bord était donc inférieure au nombre réel de candidatures — un
   candidat en cours de test disparaissait des chiffres.
2. **La regex du schéma n'admettait que quatre valeurs**, alors que le code en
   écrivait quatre autres directement sur le modèle. Un RH ne pouvait pas poser
   un statut que l'application elle-même produisait.

S'y ajoute ce que le vocabulaire apporte de neuf : des transitions vérifiées.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import application_status as st
from app.models.application_status import ApplicationStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole
from app.services.analytics_service import APPLICATION_STATUSES
from app.services.notification_service import APPLICATION_STATUS_LABELS
from app.services.pdf_service import STATUS_LABELS

from tests.conftest import VALID_PASSWORD


# ── Une seule source ──────────────────────────────────────────────────────────

def test_les_quatre_declarations_derivent_de_la_meme_liste():
    """
    Le cœur du lot. Si l'une de ces égalités casse, quelqu'un a réintroduit une
    liste parallèle — et le décompte du tableau de bord recommencera à mentir.
    """
    assert APPLICATION_STATUSES == st.ALL
    assert APPLICATION_STATUS_LABELS is st.LABELS_FR
    assert STATUS_LABELS is st.LABELS_FR
    assert set(st.LABELS_FR) == {s.value for s in ApplicationStatus}


def test_les_statuts_produits_par_le_code_sont_dans_le_vocabulaire():
    """Régression : TEST_SENT et HIRED étaient écrits mais jamais comptés."""
    for produit in ("TEST_SENT", "EN_TEST", "TEST_DONE", "HIRED",
                    "NEGOTIATION", "INTERVIEW_SCHEDULED"):
        assert produit in APPLICATION_STATUSES, (
            f"« {produit} » est écrit par le code mais absent des statistiques"
        )


def test_chaque_statut_a_un_libelle_francais():
    for valeur in st.ALL:
        assert st.label(valeur) != valeur, f"« {valeur} » afficherait sa clé brute"


def test_un_statut_inconnu_ne_casse_pas_laffichage():
    """Des données historiques peuvent précéder ce vocabulaire."""
    assert st.label("VIEUX_STATUT") == "VIEUX_STATUT"
    assert st.label(None) == "—"
    assert st.label("") == "—"


# ── Transitions ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("depart,arrivee", [
    ("PENDING", "REVIEWED"),
    ("REVIEWED", "TEST_SENT"),
    ("TEST_SENT", "EN_TEST"),
    ("EN_TEST", "TEST_DONE"),
    ("TEST_DONE", "INTERVIEW_SCHEDULED"),
    ("INTERVIEW_SCHEDULED", "NEGOTIATION"),
    ("NEGOTIATION", "ACCEPTED"),
    ("ACCEPTED", "HIRED"),
])
def test_le_parcours_nominal_passe(depart, arrivee):
    assert st.can_transition(depart, arrivee)


def test_le_rh_peut_sauter_le_test():
    """
    Rencontrer quelqu'un sans le faire passer par le test reste possible : le
    test informe la décision, il ne la prend pas.
    """
    assert st.can_transition("REVIEWED", "INTERVIEW_SCHEDULED")


def test_un_lien_jamais_ouvert_peut_etre_corrige_en_letat():
    """Le balayage clôt une session envoyée et jamais ouverte."""
    assert st.can_transition("TEST_SENT", "TEST_DONE")


@pytest.mark.parametrize("depart,arrivee", [
    ("PENDING", "ACCEPTED"),              # CV lu hors de l'outil
    ("PENDING", "HIRED"),                 # embauche directe, cooptation
    ("REVIEWED", "INTERVIEW_SCHEDULED"),  # sauter le test
    ("EN_TEST", "INTERVIEW_SCHEDULED"),   # ne pas attendre la fin du test
])
def test_avancer_reste_libre_meme_en_sautant_des_etapes(depart, arrivee):
    """
    La règle est permissive vers l'avant, délibérément. Un RH qui accepte
    directement quelqu'un fait son métier ; lui opposer un formalisme que le
    produit n'a jamais eu serait une régression déguisée en rigueur.
    """
    assert st.can_transition(depart, arrivee)


@pytest.mark.parametrize("depart,arrivee", [
    ("ACCEPTED", "PENDING"),
    ("INTERVIEW_SCHEDULED", "REVIEWED"),
    ("TEST_DONE", "TEST_SENT"),
])
def test_reculer_est_refuse(depart, arrivee):
    """
    Le vrai garde-fou : un clic maladroit ne doit pas renvoyer une candidature
    en arrière et effacer l'historique visible du parcours.
    """
    assert not st.can_transition(depart, arrivee)


def test_un_second_entretien_est_possible():
    assert st.can_transition("INTERVIEW_SCHEDULED", "INTERVIEW_SCHEDULED")


def test_une_negociation_qui_echoue_ramene_a_lentretien():
    assert st.can_transition("NEGOTIATION", "INTERVIEW_SCHEDULED")


def test_on_peut_rejeter_a_tout_moment():
    for depart in st.ALL:
        if depart in st.TERMINAL:
            continue
        assert st.can_transition(depart, "REJECTED"), depart


def test_un_etat_terminal_ne_se_rouvre_pas():
    """Un candidat recruté ou rejeté ne repart pas dans le parcours."""
    assert not st.can_transition("HIRED", "REJECTED")
    assert not st.can_transition("REJECTED", "PENDING")
    assert not st.can_transition("HIRED", "NEGOTIATION")


def test_un_refus_de_contrat_rouvre_la_negociation():
    """Le candidat accepté peut refuser : on ne le perd pas pour autant."""
    assert st.can_transition("ACCEPTED", "NEGOTIATION")


def test_un_statut_inconnu_en_depart_ne_bloque_pas():
    """Des candidatures antérieures au vocabulaire doivent rester modifiables."""
    assert st.can_transition("VIEUX_STATUT", "REVIEWED")
    assert not st.can_transition("VIEUX_STATUT", "NIMPORTEQUOI")


# ── Bout en bout par l'API ────────────────────────────────────────────────────

async def _contexte(db: AsyncSession) -> tuple[Application, str]:
    job = JobOffer(title="Développeur", description="Poste de test.",
                   is_active=True, status="PUBLISHED")
    db.add(job)
    await db.flush()

    suffixe = uuid.uuid4().hex[:8]
    user = User(email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD),
                full_name="Candidat", is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name="Candidat")
    db.add(candidat)
    await db.flush()
    app_ = Application(candidate_id=candidat.id, job_offer_id=job.id,
                       cv_file_path="/tmp/cv.pdf",
                       status=ApplicationStatus.REVIEWED.value)
    db.add(app_)

    rh_suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{rh_suffixe}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, username=f"rh_{rh_suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
                role=UserRole.ADMIN, is_active=True, is_verified=True))
    await db.commit()
    await db.refresh(app_)
    return app_, email


async def _entete(client: AsyncClient, email: str) -> dict[str, str]:
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_lapi_accepte_un_statut_que_le_code_produit(
    client: AsyncClient, db: AsyncSession
):
    """
    Régression : la regex limitait le RH à quatre valeurs, alors que
    l'application elle-même en écrivait d'autres. Poser « Test envoyé » à la
    main renvoyait 422.
    """
    app_, email = await _contexte(db)
    resp = await client.patch(
        f"/api/v1/recruitment/applications/{app_.id}",
        json={"status": "TEST_SENT"},
        headers=await _entete(client, email),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "TEST_SENT"


@pytest.mark.asyncio
async def test_lapi_refuse_un_statut_hors_vocabulaire(
    client: AsyncClient, db: AsyncSession
):
    app_, email = await _contexte(db)
    resp = await client.patch(
        f"/api/v1/recruitment/applications/{app_.id}",
        json={"status": "TOTALEMENT_INVENTE"},
        headers=await _entete(client, email),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_lapi_refuse_de_faire_reculer_une_candidature(
    client: AsyncClient, db: AsyncSession
):
    """
    Avancer reste libre ; c'est reculer qui est refusé. Un clic maladroit ne
    doit pas renvoyer en attente une candidature déjà arrivée à l'entretien.
    """
    app_, email = await _contexte(db)
    entete = await _entete(client, email)

    avance = await client.patch(f"/api/v1/recruitment/applications/{app_.id}",
                                json={"status": "INTERVIEW_SCHEDULED"},
                                headers=entete)
    assert avance.status_code == 200, avance.text

    recul = await client.patch(f"/api/v1/recruitment/applications/{app_.id}",
                               json={"status": "PENDING"}, headers=entete)
    assert recul.status_code == 409
    assert "impossible" in recul.json()["detail"].lower()


@pytest.mark.asyncio
async def test_lapi_laisse_accepter_directement(
    client: AsyncClient, db: AsyncSession
):
    """Régression à ne pas créer : le RH pouvait le faire, il doit le pouvoir."""
    app_, email = await _contexte(db)
    resp = await client.patch(f"/api/v1/recruitment/applications/{app_.id}",
                              json={"status": "ACCEPTED"},
                              headers=await _entete(client, email))
    assert resp.status_code == 200, resp.text
