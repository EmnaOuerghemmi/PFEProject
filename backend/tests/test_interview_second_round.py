"""
Un second entretien avec le même candidat, une fois le premier passé.

Il n'existe pas de statut « terminé » : un entretien tenu reste CONFIRMED pour
toujours. Ce statut bloquait donc toute nouvelle invitation, alors qu'un second
entretien est courant. La règle est désormais portée par la FIN du créneau
retenu :

* entretien confirmé ET passé  → il reste au dossier, il ne bloque plus ;
* entretien confirmé, à venir ou en cours → toujours bloqué (409), il faut
  l'annuler pour replanifier ;
* invitation en attente → remplacée, comme avant.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.models.application_status import ApplicationStatus
from app.models.interview import InterviewInvitation, InterviewSlot, InvitationStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.interview_service import entretien_termine

from tests.conftest import VALID_PASSWORD


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


async def _rh(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
                role=UserRole.RH, is_active=True, is_verified=True))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _candidature(db: AsyncSession) -> Application:
    suffixe = uuid.uuid4().hex[:8]
    user = User(email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Test",
                is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name="Candidat Test")
    job = JobOffer(title="Développeur", description="Poste de test.",
                   required_skills=["Python"], required_experience_years=2,
                   is_active=True, status="PUBLISHED")
    db.add_all([candidat, job])
    await db.flush()
    candidature = Application(candidate_id=candidat.id, job_offer_id=job.id,
                              cv_file_path="/tmp/cv.pdf",
                              status=ApplicationStatus.INTERVIEW_SCHEDULED.value)
    db.add(candidature)
    await db.flush()
    db.add(CandidateScore(
        application_id=candidature.id, job_offer_id=job.id, candidate_id=candidat.id,
        total_score=70, skills_score=70, experience_score=70, education_score=70,
    ))
    await db.commit()
    await db.refresh(candidature)
    return candidature


async def _invitation(
    db: AsyncSession, candidature: Application, *, statut: InvitationStatus,
    debut: datetime | None, duree_min: int = 45, creee_il_y_a: timedelta = timedelta(0),
    creneau_retenu: bool = True,
) -> InterviewInvitation:
    invitation = InterviewInvitation(
        application_id=candidature.id, token=uuid.uuid4().hex, status=statut,
        expires_at=_maintenant() + timedelta(days=2),
        confirmed_at=_maintenant() if statut == InvitationStatus.CONFIRMED else None,
    )
    db.add(invitation)
    await db.flush()
    if debut is not None:
        db.add(InterviewSlot(
            invitation_id=invitation.id, start_at=debut,
            end_at=debut + timedelta(minutes=duree_min), is_selected=creneau_retenu,
        ))
    await db.commit()
    await db.refresh(invitation)
    if creee_il_y_a:
        invitation.created_at = _maintenant() - creee_il_y_a
        await db.commit()
    return invitation


async def _planifier(client: AsyncClient, entetes: dict, candidature: Application):
    return await client.post(
        f"/api/v1/recruitment/applications/{candidature.id}/schedule-interview",
        json={"slots": [(_maintenant() + timedelta(days=3)).isoformat()]},
        headers=entetes,
    )


async def _invitations(db: AsyncSession, candidature: Application) -> list[InterviewInvitation]:
    # Identifiant lu AVANT d'expirer la session : relire un attribut expiré
    # déclencherait une requête synchrone, interdite en asynchrone.
    app_id = candidature.id
    db.expire_all()
    return list((await db.execute(
        select(InterviewInvitation).where(InterviewInvitation.application_id == app_id)
        .order_by(InterviewInvitation.created_at)
    )).scalars().all())


# ── Ce qui bloque, ce qui ne bloque plus ──────────────────────────────────────

@pytest.mark.asyncio
async def test_un_entretien_deja_passe_ne_bloque_plus_un_second(client: AsyncClient, db: AsyncSession):
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    premier = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                                debut=_maintenant() - timedelta(days=2))

    resp = await _planifier(client, entetes, candidature)

    assert resp.status_code == 200, resp.text
    toutes = await _invitations(db, candidature)
    assert len(toutes) == 2
    # Le premier reste au dossier, tel quel : c'est l'historique de ce qui s'est tenu.
    ancien = next(i for i in toutes if i.id == premier.id)
    assert ancien.status == InvitationStatus.CONFIRMED
    assert any(i.status == InvitationStatus.PENDING for i in toutes)


@pytest.mark.asyncio
async def test_un_entretien_a_venir_bloque_toujours(client: AsyncClient, db: AsyncSession):
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() + timedelta(days=2))

    resp = await _planifier(client, entetes, candidature)

    assert resp.status_code == 409
    assert "pas encore eu lieu" in resp.json()["detail"]
    assert len(await _invitations(db, candidature)) == 1


@pytest.mark.asyncio
async def test_un_entretien_en_cours_bloque_encore(client: AsyncClient, db: AsyncSession):
    """Commencé il y a dix minutes, il dure trois quarts d'heure : pas fini."""
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() - timedelta(minutes=10), duree_min=45)

    assert (await _planifier(client, entetes, candidature)).status_code == 409


@pytest.mark.asyncio
async def test_sans_creneau_retenu_on_ne_sait_pas_quand_il_a_lieu(client: AsyncClient, db: AsyncSession):
    """Le considérer comme passé laisserait ouvrir un doublon."""
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() - timedelta(days=2), creneau_retenu=False)

    assert (await _planifier(client, entetes, candidature)).status_code == 409


@pytest.mark.asyncio
async def test_une_invitation_en_attente_reste_remplacee(client: AsyncClient, db: AsyncSession):
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    ancienne = await _invitation(db, candidature, statut=InvitationStatus.PENDING,
                                 debut=_maintenant() + timedelta(days=1))

    assert (await _planifier(client, entetes, candidature)).status_code == 200

    toutes = await _invitations(db, candidature)
    assert next(i for i in toutes if i.id == ancienne.id).status == InvitationStatus.CANCELLED
    assert sum(i.status == InvitationStatus.PENDING for i in toutes) == 1


# ── La règle elle-même ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_entretien_termine_se_juge_sur_la_fin_du_creneau(db: AsyncSession):
    candidature = await _candidature(db)
    maintenant = _maintenant()
    fini = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                             debut=maintenant - timedelta(minutes=50), duree_min=45)
    en_cours = await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                                 debut=maintenant - timedelta(minutes=10), duree_min=45)
    id_fini, id_en_cours = fini.id, en_cours.id   # lus avant expire_all
    db.expire_all()
    chargees = {i.id: i for i in (await db.execute(
        select(InterviewInvitation).options(selectinload(InterviewInvitation.slots))
        .where(InterviewInvitation.id.in_([id_fini, id_en_cours]))
    )).scalars().all()}

    assert entretien_termine(chargees[id_fini], maintenant) is True
    assert entretien_termine(chargees[id_en_cours], maintenant) is False


# ── Classement : c'est la plus récente qui compte ─────────────────────────────

async def _ligne(client: AsyncClient, db: AsyncSession, entetes: dict, candidature: Application) -> dict:
    resp = await client.get(f"/api/v1/recruitment/jobs/{candidature.job_offer_id}/ranking", headers=entetes)
    assert resp.status_code == 200, resp.text
    return next(l for l in resp.json()["ranking"] if l["application_id"] == str(candidature.id))


@pytest.mark.asyncio
async def test_le_classement_signale_un_entretien_passe(client: AsyncClient, db: AsyncSession):
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() - timedelta(days=1))

    ligne = await _ligne(client, db, entetes, candidature)

    assert ligne["interview_status"] == "CONFIRMED"
    assert ligne["interview_ended"] is True


@pytest.mark.asyncio
async def test_le_classement_ne_dit_pas_passe_pour_un_entretien_a_venir(client: AsyncClient, db: AsyncSession):
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() + timedelta(days=1))

    assert (await _ligne(client, db, entetes, candidature))["interview_ended"] is False


@pytest.mark.asyncio
async def test_le_classement_montre_la_nouvelle_invitation_pas_l_ancien_entretien(
        client: AsyncClient, db: AsyncSession):
    """Ancien entretien tenu (CONFIRMED) + nouvelle invitation (PENDING) : le RH
    doit voir celle qui attend le candidat."""
    entetes = await _rh(client, db)
    candidature = await _candidature(db)
    await _invitation(db, candidature, statut=InvitationStatus.CONFIRMED,
                      debut=_maintenant() - timedelta(days=5), creee_il_y_a=timedelta(days=7))
    nouvelle = await _invitation(db, candidature, statut=InvitationStatus.PENDING,
                                 debut=_maintenant() + timedelta(days=2))

    ligne = await _ligne(client, db, entetes, candidature)

    assert ligne["interview_status"] == "PENDING"
    assert ligne["interview_invitation_id"] == str(nouvelle.id)
    assert ligne["interview_ended"] is False
