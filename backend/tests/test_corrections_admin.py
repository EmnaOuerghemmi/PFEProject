"""
Corrections réservées à l'administrateur : retirer un contrat, forcer un statut.

Cas d'origine : un candidat recruté par erreur. Son contrat signé avait créé
une fiche employé et figé la candidature en « Recrutée », un état final que
rien ne permettait de quitter. Ce qui est vérifié ici :

* l'administrateur retire un contrat même signé : la candidature prend le
  statut choisi, la fiche employé passe « inactive », le journal d'audit garde
  la trace (motif compris) ;
* il peut ensuite corriger le statut, hors des règles de parcours ;
* le RH ne peut faire ni l'un ni l'autre ;
* garde-fous : pas de statut forcé tant qu'un contrat est envoyé ou signé, et
  « Recrutée » ne se force jamais.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.employee import Employee
from app.models.recruitment import Application
from app.models.user import AuditLog, UserRole

from tests.test_contracts import SIG_PNG, _accepted_application, _auth, _make_admin_token
from tests.test_interview_stages import _personnel


async def _contrat(client: AsyncClient, admin: str, application_id, *, signer: bool) -> str:
    """Crée le contrat d'une candidature acceptée, l'envoie, et le fait signer si demandé."""
    c = (await client.post(f"/api/v1/contracts/from-application/{application_id}",
                           json={"contract_type": "CDI"}, headers=_auth(admin))).json()
    envoye = (await client.post(f"/api/v1/contracts/{c['id']}/send", json={}, headers=_auth(admin))).json()
    if signer:
        jeton = envoye["public_url"].rsplit("/", 1)[-1]
        resp = await client.post(f"/api/v1/contracts/sign/{jeton}",
                                 json={"signer_name": "Sarra Ben Ali", "signature_image": SIG_PNG, "consent": True})
        assert resp.status_code == 200, resp.text
    return c["id"]


async def _statut(db: AsyncSession, application_id) -> str:
    return (await db.execute(select(Application.status).where(Application.id == application_id))).scalar_one()


@pytest.mark.asyncio
async def test_l_admin_retire_un_contrat_signe(client: AsyncClient, db: AsyncSession):
    _, admin = await _make_admin_token(client, db, email=f"adm_{uuid.uuid4().hex[:6]}@ex.com")
    candidature, candidat = await _accepted_application(db)
    # Lus AVANT `expire_all` : relire un attribut expiré lancerait une requête
    # implicite, interdite en asynchrone.
    application_id, email_candidat = candidature.id, candidat.email
    contrat_id = await _contrat(client, admin, application_id, signer=True)
    assert await _statut(db, application_id) == "HIRED"

    resp = await client.post(f"/api/v1/contracts/{contrat_id}/retirer",
                             json={"motif": "Recrutement annulé par la direction", "statut_candidature": "ON_HOLD"},
                             headers=_auth(admin))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"application_id": str(application_id), "application_status": "ON_HOLD",
                           "employe_desactive": True}
    db.expire_all()
    assert (await db.execute(select(Contract).where(Contract.id == uuid.UUID(contrat_id)))).scalar_one_or_none() is None
    assert await _statut(db, application_id) == "ON_HOLD"
    employe = (await db.execute(select(Employee).where(Employee.email == email_candidat))).scalar_one()
    assert employe.status == "inactive", "la fiche reste, inactive : l'historique RH n'est pas effacé"

    trace = (await db.execute(select(AuditLog).where(AuditLog.action == "CONTRACT_WITHDRAWN"))).scalar_one()
    assert trace.resource_id == contrat_id
    assert trace.details["statut_contrat"] == "ACTIVE"
    assert trace.details["statut_candidature"] == {"avant": "HIRED", "apres": "ON_HOLD"}
    assert trace.details["motif"] == "Recrutement annulé par la direction"


@pytest.mark.asyncio
async def test_le_rh_ne_peut_ni_retirer_ni_forcer(client: AsyncClient, db: AsyncSession):
    _, admin = await _make_admin_token(client, db, email=f"adm_{uuid.uuid4().hex[:6]}@ex.com")
    rh, _ = await _personnel(client, db, UserRole.RH)
    candidature, _ = await _accepted_application(db)
    contrat_id = await _contrat(client, admin, candidature.id, signer=True)

    retrait = await client.post(f"/api/v1/contracts/{contrat_id}/retirer",
                                json={"motif": "Essai du RH"}, headers=rh)
    force = await client.post(f"/api/v1/recruitment/applications/{candidature.id}/statut-force",
                              json={"status": "REVIEWED", "motif": "Essai du RH"}, headers=rh)

    assert retrait.status_code == 403
    assert force.status_code == 403


@pytest.mark.asyncio
async def test_l_admin_corrige_un_statut_final(client: AsyncClient, db: AsyncSession):
    """Un rejet par erreur : « Rejetée » est un état final pour le RH, pas pour l'admin."""
    _, admin = await _make_admin_token(client, db, email=f"adm_{uuid.uuid4().hex[:6]}@ex.com")
    candidature, _ = await _accepted_application(db)
    candidature.status = "REJECTED"
    await db.commit()

    resp = await client.post(f"/api/v1/recruitment/applications/{candidature.id}/statut-force",
                             json={"status": "REVIEWED", "motif": "Rejet envoyé par erreur"}, headers=_auth(admin))

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "REVIEWED"
    trace = (await db.execute(select(AuditLog).where(AuditLog.action == "APPLICATION_STATUS_FORCED"))).scalar_one()
    assert trace.details == {"avant": "REJECTED", "apres": "REVIEWED", "motif": "Rejet envoyé par erreur"}


@pytest.mark.asyncio
async def test_pas_de_statut_force_tant_qu_un_contrat_est_en_cours(client: AsyncClient, db: AsyncSession):
    _, admin = await _make_admin_token(client, db, email=f"adm_{uuid.uuid4().hex[:6]}@ex.com")
    candidature, _ = await _accepted_application(db)
    await _contrat(client, admin, candidature.id, signer=False)   # envoyé, pas encore signé

    resp = await client.post(f"/api/v1/recruitment/applications/{candidature.id}/statut-force",
                             json={"status": "REJECTED", "motif": "Le poste est pourvu"}, headers=_auth(admin))

    assert resp.status_code == 409
    assert "retirez-le d'abord" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_recrutee_ne_se_force_pas_et_le_motif_est_exige(client: AsyncClient, db: AsyncSession):
    _, admin = await _make_admin_token(client, db, email=f"adm_{uuid.uuid4().hex[:6]}@ex.com")
    candidature, _ = await _accepted_application(db)
    url = f"/api/v1/recruitment/applications/{candidature.id}/statut-force"

    recrutee = await client.post(url, json={"status": "HIRED", "motif": "Passage direct"}, headers=_auth(admin))
    sans_motif = await client.post(url, json={"status": "REVIEWED", "motif": "x"}, headers=_auth(admin))

    assert recrutee.status_code == 409
    assert sans_motif.status_code == 422
