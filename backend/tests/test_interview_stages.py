"""
Étapes d'un entretien, membres, et droit de l'évaluer.

L'écran des entretiens range ses cartes par ÉTAPE (à venir, à évaluer,
évalué, en attente de réponse, candidat absent, annulé), calculée ici.

Un entretien a des membres — ceux qui le mènent :

* un recruteur ne voit que les entretiens dont il est membre ;
* seuls les membres peuvent l'évaluer ; sans membre, le RH le peut ;
* l'évaluation est marquée sur l'entretien, pour qu'un second entretien du
  même candidat ne paraisse pas déjà évalué.
"""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.interview import InterviewInvitation, InvitationStatus, interview_members
from app.models.user import User, UserRole
from app.services.interview_service import etape_entretien, peut_evaluer

from tests.conftest import VALID_PASSWORD
from tests.test_interview_second_round import _candidature, _invitation, _maintenant


async def _personnel(client: AsyncClient, db: AsyncSession, role: UserRole) -> tuple[dict, uuid.UUID]:
    suffixe = uuid.uuid4().hex[:6]
    email = f"{role.lower()}_{suffixe}@example.com"
    user = User(id=uuid.uuid4(), email=email, username=f"p_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name=f"Personnel {suffixe}",
                role=role, is_active=True, is_verified=True)
    db.add(user)
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user.id


async def _ajouter_membre(db: AsyncSession, invitation: InterviewInvitation, user_id: uuid.UUID) -> None:
    await db.execute(interview_members.insert().values(invitation_id=invitation.id, user_id=user_id))
    await db.commit()
    # Le test et l'API partagent la session : sans cela, l'invitation garderait
    # en mémoire sa liste de membres d'avant l'insertion directe ci-dessus.
    db.expire(invitation, ["membres"])


async def _liste(client: AsyncClient, entetes: dict) -> dict[str, dict]:
    resp = await client.get("/api/v1/interview/invitations", headers=entetes)
    assert resp.status_code == 200, resp.text
    return {item["id"]: item for item in resp.json()}


# ── Étapes (calcul pur) ───────────────────────────────────────────────────────

def _inv(statut: InvitationStatus, *, fin_dans: timedelta | None = None, expire_dans=timedelta(days=1),
         evaluee: bool = False):
    maintenant = _maintenant()
    creneaux = []
    if fin_dans is not None:
        fin = maintenant + fin_dans
        creneaux = [SimpleNamespace(is_selected=True, start_at=fin - timedelta(minutes=30), end_at=fin)]
    return SimpleNamespace(status=statut, expires_at=maintenant + expire_dans, slots=creneaux,
                           evaluated_at=maintenant if evaluee else None)


def test_etape_a_venir_puis_a_evaluer_puis_evalue():
    assert etape_entretien(_inv(InvitationStatus.CONFIRMED, fin_dans=timedelta(hours=2))) == "A_VENIR"
    assert etape_entretien(_inv(InvitationStatus.CONFIRMED, fin_dans=-timedelta(hours=2))) == "A_EVALUER"
    assert etape_entretien(_inv(InvitationStatus.CONFIRMED, fin_dans=-timedelta(hours=2), evaluee=True)) == "EVALUE"


def test_un_entretien_en_cours_reste_a_venir():
    # Commencé il y a dix minutes, fini dans vingt : on ne note pas quelqu'un qu'on écoute.
    assert etape_entretien(_inv(InvitationStatus.CONFIRMED, fin_dans=timedelta(minutes=20))) == "A_VENIR"


def test_sans_reponse_a_l_echeance_le_candidat_est_absent():
    assert etape_entretien(_inv(InvitationStatus.PENDING)) == "EN_ATTENTE"
    # Le balayage de fond n'est pas encore passé : l'échéance fait foi.
    assert etape_entretien(_inv(InvitationStatus.PENDING, expire_dans=-timedelta(minutes=1))) == "ABSENT"
    assert etape_entretien(_inv(InvitationStatus.EXPIRED)) == "ABSENT"


def test_annule():
    assert etape_entretien(_inv(InvitationStatus.CANCELLED)) == "ANNULE"


# ── Droit d'évaluer (calcul pur) ──────────────────────────────────────────────

def _personne(role: UserRole, *, superuser: bool = False):
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_superuser=superuser)


def test_seuls_les_membres_evaluent():
    membre, rh = _personne(UserRole.RECRUTEUR), _personne(UserRole.RH)
    inv = SimpleNamespace(membres=[membre], created_by=rh.id)
    assert peut_evaluer(inv, membre)
    assert not peut_evaluer(inv, rh)          # même le créateur, s'il n'est pas membre
    assert not peut_evaluer(inv, _personne(UserRole.ADMIN))
    assert peut_evaluer(inv, _personne(UserRole.ADMIN, superuser=True))


def test_sans_membre_le_rh_evalue():
    createur = _personne(UserRole.RECRUTEUR)
    inv = SimpleNamespace(membres=[], created_by=createur.id)
    assert peut_evaluer(inv, _personne(UserRole.RH))
    assert peut_evaluer(inv, _personne(UserRole.ADMIN))
    assert peut_evaluer(inv, createur)
    assert not peut_evaluer(inv, _personne(UserRole.RECRUTEUR))


# ── Visibilité ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_recruteur_ne_voit_que_ses_entretiens(client: AsyncClient, db: AsyncSession):
    entetes, recruteur_id = await _personnel(client, db, UserRole.RECRUTEUR)
    candidature = await _candidature(db)
    le_sien = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                                debut=_maintenant() + timedelta(days=1))
    await _ajouter_membre(db, le_sien, recruteur_id)
    autre = await _invitation(db, await _candidature(db), statut=InvitationStatus.CONFIRMED,
                              debut=_maintenant() + timedelta(days=2))

    liste = await _liste(client, entetes)

    assert str(le_sien.id) in liste
    assert str(autre.id) not in liste
    detail = await client.get(f"/api/v1/interview/invitations/{autre.id}", headers=entetes)
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_le_rh_voit_tout_et_l_etape_est_renvoyee(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    inv = await _invitation(db, await _candidature(db), statut=InvitationStatus.CONFIRMED,
                            debut=_maintenant() + timedelta(days=1))

    item = (await _liste(client, entetes))[str(inv.id)]

    assert item["stage"] == "A_VENIR"
    assert item["members"] == []
    assert item["job_offer_id"]
    assert item["application_status"] == "INTERVIEW_SCHEDULED"


@pytest.mark.asyncio
async def test_les_entretiens_clos_depuis_plus_de_30_jours_sont_masques(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    ancien = await _invitation(db, await _candidature(db), statut=InvitationStatus.CANCELLED, debut=None)
    ancien.cancelled_at = _maintenant() - timedelta(days=31)
    recent = await _invitation(db, await _candidature(db), statut=InvitationStatus.EXPIRED, debut=None)
    recent.expires_at = _maintenant() - timedelta(days=3)
    await db.commit()

    liste = await _liste(client, entetes)

    assert str(ancien.id) not in liste
    assert liste[str(recent.id)]["stage"] == "ABSENT"


# ── Planification avec plusieurs membres ──────────────────────────────────────

@pytest.mark.asyncio
async def test_planifier_avec_plusieurs_membres(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    _, r1 = await _personnel(client, db, UserRole.RECRUTEUR)
    _, r2 = await _personnel(client, db, UserRole.RECRUTEUR)
    candidature = await _candidature(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{candidature.id}/schedule-interview",
        json={"slots": [(_maintenant() + timedelta(days=3)).isoformat()],
              "recruiter_ids": [str(r1), str(r2)]},
        headers=entetes,
    )

    assert resp.status_code == 200, resp.text
    membres = set((await db.execute(select(interview_members.c.user_id))).scalars().all())
    assert {r1, r2} <= membres


@pytest.mark.asyncio
async def test_un_recruteur_qui_planifie_en_est_membre(client: AsyncClient, db: AsyncSession):
    entetes, recruteur_id = await _personnel(client, db, UserRole.RECRUTEUR)
    candidature = await _candidature(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{candidature.id}/schedule-interview",
        json={"slots": [(_maintenant() + timedelta(days=3)).isoformat()]},
        headers=entetes,
    )

    assert resp.status_code == 200, resp.text
    # Sinon l'entretien disparaîtrait de sa propre liste aussitôt créé.
    assert len(await _liste(client, entetes)) == 1


@pytest.mark.asyncio
async def test_un_candidat_ne_peut_pas_etre_membre(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    _, candidat_id = await _personnel(client, db, UserRole.CANDIDAT)
    candidature = await _candidature(db)

    resp = await client.post(
        f"/api/v1/recruitment/applications/{candidature.id}/schedule-interview",
        json={"slots": [(_maintenant() + timedelta(days=3)).isoformat()],
              "recruiter_ids": [str(candidat_id)]},
        headers=entetes,
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.RECRUTEUR, UserRole.RH])
async def test_les_membres_possibles_sans_acces_aux_comptes(client: AsyncClient, db: AsyncSession, role):
    """Planifier un entretien ne demande pas `users:read` (réservé à l'admin) :
    la liste des membres possibles a sa propre route, limitée au personnel actif."""
    entetes, moi = await _personnel(client, db, role)
    _, collegue = await _personnel(client, db, UserRole.RECRUTEUR)
    _, candidat = await _personnel(client, db, UserRole.CANDIDAT)
    _, parti = await _personnel(client, db, UserRole.RH)
    (await db.get(User, parti)).is_active = False
    await db.commit()

    assert (await client.get("/api/v1/users", headers=entetes)).status_code == 403
    resp = await client.get("/api/v1/interview/membres-possibles", headers=entetes)

    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()}
    assert {str(moi), str(collegue)} <= ids
    assert str(candidat) not in ids and str(parti) not in ids
    assert set(resp.json()[0]) == {"id", "name", "email"}


@pytest.mark.asyncio
async def test_un_candidat_ne_liste_pas_les_membres_possibles(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.CANDIDAT)
    assert (await client.get("/api/v1/interview/membres-possibles", headers=entetes)).status_code == 403


# ── Évaluation réservée aux membres ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_seul_un_membre_peut_noter_et_l_entretien_passe_en_evalue(client: AsyncClient, db: AsyncSession):
    entetes_membre, membre_id = await _personnel(client, db, UserRole.RECRUTEUR)
    entetes_rh, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    inv = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                            debut=_maintenant() - timedelta(days=1))
    await _ajouter_membre(db, inv, membre_id)
    url = f"/api/v1/assessment/applications/{candidature.id}/interview/score"

    refus = await client.post(url, json={"interview_score": 70}, headers=entetes_rh)
    assert refus.status_code == 403

    assert (await _liste(client, entetes_membre))[str(inv.id)]["stage"] == "A_EVALUER"
    ok = await client.post(url, json={"interview_score": 70}, headers=entetes_membre)
    assert ok.status_code == 200, ok.text

    item = (await _liste(client, entetes_membre))[str(inv.id)]
    assert item["stage"] == "EVALUE"
    assert item["interview_score"] == 70
    assert item["can_evaluate"] is True


@pytest.mark.asyncio
async def test_un_second_entretien_n_herite_pas_de_l_evaluation_du_premier(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    premier = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                                debut=_maintenant() - timedelta(days=5))
    url = f"/api/v1/assessment/applications/{candidature.id}/interview/score"
    assert (await client.post(url, json={"interview_score": 60}, headers=entetes)).status_code == 200

    second = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                               debut=_maintenant() - timedelta(days=1))
    liste = await _liste(client, entetes)

    assert liste[str(premier.id)]["stage"] == "EVALUE"
    assert liste[str(second.id)]["stage"] == "A_EVALUER"
