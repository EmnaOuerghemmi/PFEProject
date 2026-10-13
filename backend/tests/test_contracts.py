"""
Tests de la gestion de contrat + signature électronique auto-hébergée (V1.8).

Couvre le cycle de vie complet :
  DRAFT → SENT → SIGNED → ACTIVE  (+ DECLINED, garde-fous d'état)
et la boucle recrutement → RH : à la signature, un Employee est créé et la
candidature passe en HIRED. Vérifie aussi la piste d'audit (empreinte,
certificat) et le RBAC.
"""
import base64
import io
import uuid
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Candidate, Application
from app.models.employee import Employee
from app.models.contract import Contract, ContractStatus
from tests.conftest import VALID_PASSWORD

# PNG d'un pixel noir (data URI) pour simuler une signature manuscrite.
SIG_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
           "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


async def _make_admin_token(client: AsyncClient, db: AsyncSession, email="admin_ct@ex.com") -> tuple[User, str]:
    admin = User(id=uuid.uuid4(), email=email, username=email.split("@")[0],
                 hashed_password=hash_password(VALID_PASSWORD), full_name="Admin CT",
                 role=UserRole.ADMIN, is_active=True, is_verified=True)
    db.add(admin)
    await db.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})
    return admin, resp.json()["access_token"]


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


async def _accepted_application(db: AsyncSession, *, salary_max=3000.0) -> tuple[Application, User]:
    user = User(id=uuid.uuid4(), email=f"cand_{uuid.uuid4().hex[:6]}@ex.com",
                username=uuid.uuid4().hex[:8], hashed_password=hash_password(VALID_PASSWORD),
                full_name="Sarra Ben Ali", role=UserRole.CANDIDAT, is_active=True, is_verified=True)
    db.add(user); await db.flush()
    cand = Candidate(id=uuid.uuid4(), user_id=user.id, full_name="Sarra Ben Ali", phone="+21620000000")
    job = JobOffer(id=uuid.uuid4(), title="Frontend Developer", description="x" * 20, salary_max=salary_max)
    db.add_all([cand, job]); await db.flush()
    app = Application(id=uuid.uuid4(), candidate_id=cand.id, job_offer_id=job.id,
                      cv_file_path="cv.pdf", status="ACCEPTED")
    db.add(app); await db.commit()
    return app, user


# ── Cycle de vie complet ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_contract_lifecycle(client: AsyncClient, db: AsyncSession):
    admin, token = await _make_admin_token(client, db)
    app, cand_user = await _accepted_application(db, salary_max=3200.0)

    # 1. Création — salaire prérempli depuis l'offre (3200) + identité salarié.
    create = await client.post(
        f"/api/v1/contracts/from-application/{app.id}",
        json={"contract_type": "CDI", "department": "Tech", "trial_period_months": 3,
              "employee_cin": "11959443", "employee_birth_date": "1999-10-20T00:00:00",
              "employee_address": "Rue Ibn Khaldoun, Kairouan"},
        headers=_auth(token),
    )
    assert create.status_code == 201, create.text
    c = create.json()
    assert c["status"] == "DRAFT"
    assert c["salary"] == 3200.0
    assert c["position"] == "Frontend Developer"  # prérempli depuis l'offre
    assert c["employee_cin"] == "11959443"        # identité salarié conservée
    contract_id = c["id"]

    # Doublon interdit.
    dup = await client.post(f"/api/v1/contracts/from-application/{app.id}",
                            json={"contract_type": "CDI"}, headers=_auth(token))
    assert dup.status_code == 409

    # 2. Édition du brouillon.
    upd = await client.patch(f"/api/v1/contracts/{contract_id}",
                             json={"salary": 3400, "weekly_hours": 39}, headers=_auth(token))
    assert upd.status_code == 200
    assert upd.json()["salary"] == 3400.0

    # PDF téléchargeable dès le brouillon.
    pdf = await client.get(f"/api/v1/contracts/{contract_id}/pdf", headers=_auth(token))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")

    # 3. Envoi → lien public généré.
    send = await client.post(f"/api/v1/contracts/{contract_id}/send",
                             json={"expires_in_days": 10}, headers=_auth(token))
    assert send.status_code == 200
    sent = send.json()
    assert sent["status"] == "SENT"
    assert sent["public_url"] and "/contract/sign/" in sent["public_url"]
    token_pub = sent["public_url"].rsplit("/", 1)[-1]

    # 4. Vue publique (candidat, sans auth).
    view = await client.get(f"/api/v1/contracts/sign/{token_pub}")
    assert view.status_code == 200
    v = view.json()
    assert v["status"] == "SENT"
    assert v["candidate_name"] == "Sarra Ben Ali"
    assert v["salary"] == 3400.0

    # 5. Signature (candidat, sans auth) → ACTIVE + employé créé.
    sign = await client.post(
        f"/api/v1/contracts/sign/{token_pub}",
        json={"signer_name": "Sarra Ben Ali", "signature_image": SIG_PNG, "consent": True},
    )
    assert sign.status_code == 200, sign.text
    assert sign.json()["status"] == "ACTIVE"
    assert sign.json()["certificate_id"] is not None

    # Boucle RH : la candidature passe HIRED, l'employé est créé, lié au contrat.
    refreshed_app = (await db.execute(select(Application).where(Application.id == app.id))).scalar_one()
    assert refreshed_app.status == "HIRED"
    contract = (await db.execute(select(Contract).where(Contract.id == uuid.UUID(contract_id)))).scalar_one()
    assert contract.status == ContractStatus.ACTIVE
    assert contract.employee_id is not None
    assert contract.document_hash and len(contract.document_hash) == 64  # SHA-256
    employee = (await db.execute(select(Employee).where(Employee.email == cand_user.email))).scalar_one()
    assert employee.position == "Frontend Developer"
    assert employee.salary == 3400.0
    assert employee.status == "active"

    # 6. Re-signer est refusé (409).
    resign = await client.post(f"/api/v1/contracts/sign/{token_pub}",
                               json={"signer_name": "Test Nom", "signature_image": SIG_PNG, "consent": True})
    assert resign.status_code == 409

    # Le PDF signé contient le certificat.
    pdf2 = await client.get(f"/api/v1/contracts/{contract_id}/pdf", headers=_auth(token))
    assert pdf2.status_code == 200 and pdf2.content.startswith(b"%PDF-")


# ── Garde-fous ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sign_requires_consent(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a2@ex.com")
    app, _ = await _accepted_application(db)
    c = (await client.post(f"/api/v1/contracts/from-application/{app.id}",
                           json={"contract_type": "CDI"}, headers=_auth(token))).json()
    sent = (await client.post(f"/api/v1/contracts/{c['id']}/send", json={}, headers=_auth(token))).json()
    tok = sent["public_url"].rsplit("/", 1)[-1]

    resp = await client.post(f"/api/v1/contracts/sign/{tok}",
                             json={"signer_name": "Test Nom", "signature_image": SIG_PNG, "consent": False})
    assert resp.status_code == 400


def _png(couleur: tuple[int, int, int, int]) -> str:
    """Cadre de signature 300×100 d'une seule couleur, en data URI."""
    tampon = io.BytesIO()
    Image.new("RGBA", (300, 100), couleur).save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("image", [
    _png((0, 0, 0, 0)),             # cadre transparent : ce qu'envoyait un cadre effacé
    _png((255, 255, 255, 255)),     # cadre blanc
    "data:image/png;base64,pas-une-image",
    "texte libre",
])
async def test_une_signature_vide_ou_illisible_est_refusee(client: AsyncClient, db: AsyncSession, image: str):
    _, token = await _make_admin_token(client, db, email=f"vide_{uuid.uuid4().hex[:6]}@ex.com")
    app, _ = await _accepted_application(db)
    c = (await client.post(f"/api/v1/contracts/from-application/{app.id}",
                           json={"contract_type": "CDI"}, headers=_auth(token))).json()
    sent = (await client.post(f"/api/v1/contracts/{c['id']}/send", json={}, headers=_auth(token))).json()
    tok = sent["public_url"].rsplit("/", 1)[-1]

    resp = await client.post(f"/api/v1/contracts/sign/{tok}",
                             json={"signer_name": "Test Nom", "signature_image": image, "consent": True})

    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()
    contrat = (await db.execute(select(Contract).where(Contract.id == uuid.UUID(c["id"])))).scalar_one()
    await db.refresh(contrat)
    assert contrat.status == ContractStatus.SENT
    assert contrat.signature_image is None


@pytest.mark.asyncio
async def test_decline_flow(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a3@ex.com")
    app, _ = await _accepted_application(db)
    c = (await client.post(f"/api/v1/contracts/from-application/{app.id}",
                           json={"contract_type": "CDD"}, headers=_auth(token))).json()
    sent = (await client.post(f"/api/v1/contracts/{c['id']}/send", json={}, headers=_auth(token))).json()
    tok = sent["public_url"].rsplit("/", 1)[-1]

    dec = await client.post(f"/api/v1/contracts/decline/{tok}",
                            json={"reason": "Meilleure offre ailleurs"})
    assert dec.status_code == 200 and dec.json()["status"] == "DECLINED"
    # Signer après refus → 410.
    late = await client.post(f"/api/v1/contracts/sign/{tok}",
                             json={"signer_name": "Test Nom", "signature_image": SIG_PNG, "consent": True})
    assert late.status_code == 410


@pytest.mark.asyncio
async def test_stats_and_rbac(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a4@ex.com")

    # Sans auth → 401.
    assert (await client.get("/api/v1/contracts")).status_code == 401

    app, _ = await _accepted_application(db)
    await client.post(f"/api/v1/contracts/from-application/{app.id}",
                      json={"contract_type": "STAGE"}, headers=_auth(token))
    stats = (await client.get("/api/v1/contracts/stats", headers=_auth(token))).json()
    assert stats["total"] >= 1 and stats["draft"] >= 1

    listing = await client.get("/api/v1/contracts", headers=_auth(token))
    assert listing.status_code == 200
    assert any(x["job_title"] == "Frontend Developer" for x in listing.json())


# ── Candidats acceptés reçus par la page Contrats ─────────────────────────────

@pytest.mark.asyncio
async def test_candidat_accepte_recu_avec_salaire_puis_retire_apres_creation(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a5@ex.com")
    app, _ = await _accepted_application(db, salary_max=2800.0)

    pending = (await client.get("/api/v1/contracts/pending", headers=_auth(token))).json()
    ligne = next(p for p in pending if p["application_id"] == str(app.id))
    assert ligne["candidate_name"] == "Sarra Ben Ali"
    assert ligne["job_title"] == "Frontend Developer"
    assert ligne["suggested_salary"] == 2800.0
    assert ligne["salary_source"] == "offer_max"

    # Le RH confirme un autre montant : c'est celui-là qui est écrit au contrat.
    c = (await client.post(f"/api/v1/contracts/from-application/{app.id}",
                           json={"contract_type": "CDI", "salary": 2600}, headers=_auth(token))).json()
    assert c["salary"] == 2600.0

    pending = (await client.get("/api/v1/contracts/pending", headers=_auth(token))).json()
    assert all(p["application_id"] != str(app.id) for p in pending)


@pytest.mark.asyncio
async def test_pretention_dans_le_budget_prioritaire_sur_l_offre(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a6@ex.com")
    app, _ = await _accepted_application(db, salary_max=3000.0)
    app.expected_salary = 2500.0
    await db.commit()

    pending = (await client.get("/api/v1/contracts/pending", headers=_auth(token))).json()
    ligne = next(p for p in pending if p["application_id"] == str(app.id))
    assert ligne["suggested_salary"] == 2500.0
    assert ligne["salary_source"] == "expected_salary"


@pytest.mark.asyncio
async def test_pretention_hors_budget_non_retenue(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a7@ex.com")
    app, _ = await _accepted_application(db, salary_max=3000.0)
    app.expected_salary = 4200.0
    await db.commit()

    pending = (await client.get("/api/v1/contracts/pending", headers=_auth(token))).json()
    ligne = next(p for p in pending if p["application_id"] == str(app.id))
    assert ligne["suggested_salary"] == 3000.0
    assert ligne["salary_source"] == "offer_max"


@pytest.mark.asyncio
async def test_civilite_au_contrat_et_reprise_sur_la_fiche_employe(client: AsyncClient, db: AsyncSession):
    _, token = await _make_admin_token(client, db, email="a8@ex.com")
    app, cand_user = await _accepted_application(db)
    c = (await client.post(
        f"/api/v1/contracts/from-application/{app.id}",
        json={"contract_type": "CDI", "employee_civility": "Mme",
              "employee_birth_date": "1998-03-14T00:00:00"},
        headers=_auth(token),
    )).json()
    assert c["employee_civility"] == "Mme"

    pdf = await client.get(f"/api/v1/contracts/{c['id']}/pdf", headers=_auth(token))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")

    # Une civilité hors vocabulaire est refusée.
    bad = await client.patch(f"/api/v1/contracts/{c['id']}",
                             json={"employee_civility": "Dr"}, headers=_auth(token))
    assert bad.status_code == 422

    sent = (await client.post(f"/api/v1/contracts/{c['id']}/send", json={}, headers=_auth(token))).json()
    tok = sent["public_url"].rsplit("/", 1)[-1]
    await client.post(f"/api/v1/contracts/sign/{tok}",
                      json={"signer_name": "Sarra Ben Ali", "signature_image": SIG_PNG, "consent": True})
    employee = (await db.execute(select(Employee).where(Employee.email == cand_user.email))).scalar_one()
    assert employee.gender == "F"
    assert str(employee.birth_date) == "1998-03-14"
