"""
Appliquer une recommandation depuis l'aide à la décision, et vivier « en réserve ».

    Recruter   → Acceptée    (pas d'e-mail : le contrat suivra)
    Rejeter    → Rejetée     (e-mail de refus)
    En réserve → En réserve  (e-mail « candidature conservée », entrée au vivier)

Puis le vivier : un candidat en réserve est invité aux offres compatibles,
une seule fois par offre, au plus un e-mail par délai.

Le moteur de recommandation est simulé : il dépend d'index sémantiques que
la base de test ne contient pas.
"""
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_status import ApplicationStatus
from app.models.recruitment import Application, JobOffer
from app.models.talent_pool import TalentPoolEntry, TalentPoolInvitation
from app.models.user import UserRole
from app.services import talent_pool_service
from app.services.recommendation_service import recommendation_service

from tests.test_interview_second_round import _candidature, _maintenant
from tests.test_interview_stages import _personnel


def _url(app_id) -> str:
    return f"/api/v1/decision/applications/{app_id}/apply"


async def _statut(db: AsyncSession, app_id) -> str:
    # Requête sur la COLONNE : elle lit la base, sans passer par les objets en
    # mémoire. Pas d'expire_all, qui rendrait illisibles les objets du test.
    return (await db.execute(select(Application.status).where(Application.id == app_id))).scalar()


# ── Appliquer ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mettre_en_reserve(client: AsyncClient, db: AsyncSession, _aucun_email_reel):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    avant = len(_aucun_email_reel)

    resp = await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"application_id": str(candidature.id), "application_status": "ON_HOLD",
                           "email_sent": True}
    assert await _statut(db, candidature.id) == ApplicationStatus.ON_HOLD.value
    entree = (await db.execute(
        select(TalentPoolEntry).where(TalentPoolEntry.application_id == candidature.id)
    )).scalar_one()
    assert entree.candidate_id == candidature.candidate_id
    assert any("conservée" in sujet for _, sujet in _aucun_email_reel[avant:])


@pytest.mark.asyncio
async def test_rejeter_envoie_le_refus(client: AsyncClient, db: AsyncSession, _aucun_email_reel):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    avant = len(_aucun_email_reel)

    resp = await client.post(_url(candidature.id), json={"decision": "REJECT", "message": "Merci <b>beaucoup</b>"},
                             headers=entetes)

    assert resp.status_code == 200, resp.text
    assert await _statut(db, candidature.id) == ApplicationStatus.REJECTED.value
    assert len(_aucun_email_reel) == avant + 1


@pytest.mark.asyncio
async def test_recruter_passe_a_acceptee_sans_email(client: AsyncClient, db: AsyncSession, _aucun_email_reel):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    avant = len(_aucun_email_reel)

    resp = await client.post(_url(candidature.id), json={"decision": "HIRE"}, headers=entetes)

    assert resp.status_code == 200, resp.text
    assert resp.json()["email_sent"] is False
    assert await _statut(db, candidature.id) == ApplicationStatus.ACCEPTED.value
    assert len(_aucun_email_reel) == avant


@pytest.mark.asyncio
async def test_a_confirmer_ne_s_applique_pas(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)

    resp = await client.post(_url(candidature.id), json={"decision": "INTERVIEW"}, headers=entetes)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_le_recruteur_consulte_mais_n_applique_pas(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RECRUTEUR)
    candidature = await _candidature(db)

    resp = await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)

    assert resp.status_code == 403
    assert await _statut(db, candidature.id) == ApplicationStatus.INTERVIEW_SCHEDULED.value


@pytest.mark.asyncio
async def test_on_ne_recule_pas_d_acceptee_a_en_reserve(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    candidature.status = ApplicationStatus.ACCEPTED.value
    await db.commit()

    resp = await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_appliquer_deux_fois_est_refuse(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    assert (await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)).status_code == 200

    resp = await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_les_recommandations_donnent_le_statut_actuel(client: AsyncClient, db: AsyncSession):
    entetes, _ = await _personnel(client, db, UserRole.RECRUTEUR)
    candidature = await _candidature(db)

    resp = await client.get(f"/api/v1/decision/jobs/{candidature.job_offer_id}/recommendations", headers=entetes)

    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"][0]["application_status"] == "INTERVIEW_SCHEDULED"


# ── Vivier ────────────────────────────────────────────────────────────────────

async def _offre(db: AsyncSession, titre: str) -> JobOffer:
    job = JobOffer(title=titre, description="Offre de test.", required_skills=["Python"],
                   required_experience_years=1, is_active=True, status="PUBLISHED")
    db.add(job)
    await db.commit()
    return job


def _simuler_recommandations(monkeypatch, offres: list[JobOffer]):
    async def _fausse(db, candidate_id, *, limit=6):
        return [{"job_id": o.id, "title": o.title, "compatibility_score": 0.8, "reasons": []}
                for o in offres][:limit]
    monkeypatch.setattr(recommendation_service, "recommend_for_candidate", _fausse)


@pytest.mark.asyncio
async def test_le_vivier_invite_une_seule_fois_par_offre(
    client: AsyncClient, db: AsyncSession, monkeypatch, _aucun_email_reel,
):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)
    offre = await _offre(db, "Développeur Python")
    _simuler_recommandations(monkeypatch, [offre])
    avant = len(_aucun_email_reel)

    assert await talent_pool_service.inviter_sur_offres_compatibles(db) == 1
    invitations = (await db.execute(
        select(TalentPoolInvitation).where(TalentPoolInvitation.candidate_id == candidature.candidate_id)
    )).scalars().all()
    assert [i.job_offer_id for i in invitations] == [offre.id]
    assert len(_aucun_email_reel) == avant + 1

    # Même hors délai de repos, une offre déjà proposée ne l'est jamais deux fois.
    for i in invitations:
        i.sent_at = _maintenant() - timedelta(days=3)
    await db.commit()
    assert await talent_pool_service.inviter_sur_offres_compatibles(db) == 0


@pytest.mark.asyncio
async def test_le_vivier_respecte_le_delai_entre_deux_emails(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)
    premiere = await _offre(db, "Première offre")
    _simuler_recommandations(monkeypatch, [premiere])
    assert await talent_pool_service.inviter_sur_offres_compatibles(db) == 1

    seconde = await _offre(db, "Seconde offre")
    _simuler_recommandations(monkeypatch, [premiere, seconde])

    # Moins de 24 h après le premier e-mail : on attend.
    assert await talent_pool_service.inviter_sur_offres_compatibles(db) == 0


@pytest.mark.asyncio
async def test_un_candidat_sorti_de_la_reserve_n_est_plus_invite(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    entetes, _ = await _personnel(client, db, UserRole.RH)
    candidature = await _candidature(db)
    await client.post(_url(candidature.id), json={"decision": "HOLD"}, headers=entetes)
    candidature = (await db.execute(select(Application).where(Application.id == candidature.id))).scalar_one()
    candidature.status = ApplicationStatus.REJECTED.value
    await db.commit()
    _simuler_recommandations(monkeypatch, [await _offre(db, "Offre compatible")])

    assert await talent_pool_service.inviter_sur_offres_compatibles(db) == 0
