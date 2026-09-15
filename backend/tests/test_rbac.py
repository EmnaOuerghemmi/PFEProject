"""
Contrôle d'accès Casbin — ce que chaque rôle peut, et surtout ne peut pas.

Ces tests protègent trois choses distinctes :

1. **La politique elle-même** (`rbac_policy.csv`) : une ligne retirée par
   inadvertance ouvre ou ferme un pan entier de l'application sans qu'aucun
   endpoint ne change. Ils la relisent rôle par rôle.
2. **Les trois trous refermés** : le tableau de bord, la négociation salariale
   et les fichiers CV n'étaient protégés que par l'authentification. Un
   candidat connecté y accédait.
3. **Le confinement des chemins de CV** : le paramètre `:path` acceptait
   n'importe quel chemin du disque, pas seulement un CV.
"""
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import autorise, permissions_de
from app.core.security import hash_password
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole

from tests.conftest import VALID_PASSWORD


async def _compte(client: AsyncClient, db: AsyncSession, role: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    db.add(User(
        id=uuid.uuid4(), email=f"{role.lower()}_{tag}@example.com",
        username=f"{role.lower()}_{tag}", hashed_password=hash_password(VALID_PASSWORD),
        full_name=f"Compte {role}", role=role, is_active=True, is_verified=True,
    ))
    await db.commit()
    jeton = (await client.post("/api/v1/auth/login", json={
        "email": f"{role.lower()}_{tag}@example.com", "password": VALID_PASSWORD,
    })).json()["access_token"]
    return {"Authorization": f"Bearer {jeton}"}


# ── La politique, lue directement ─────────────────────────────────────────────

def test_les_quatre_roles_de_la_plateforme():
    assert UserRole.ALL == ["ADMIN", "RH", "RECRUTEUR", "CANDIDAT"]


def test_l_administrateur_peut_tout():
    for ressource in ("jobs", "users", "budget", "contracts", "n_importe_quoi"):
        for action in ("read", "write", "delete"):
            assert autorise("ADMIN", ressource, action), (ressource, action)


def test_le_recruteur_mene_le_cycle_candidat():
    """Son métier : lire les offres, traiter les candidatures, noter, tester,
    rencontrer. C'est précisément ce que l'ancien `RH_STAFF` n'avait PAS."""
    for ressource in ("applications", "scoring", "assessment", "interviews", "semantic"):
        assert autorise("RECRUTEUR", ressource, "read"), ressource
        assert autorise("RECRUTEUR", ressource, "write"), ressource
    assert autorise("RECRUTEUR", "jobs", "read")


def test_le_recruteur_n_atteint_ni_l_argent_ni_les_comptes():
    """La limite du rôle : salaires, contrats, employés, comptes utilisateurs."""
    for ressource in ("budget", "contracts", "employees", "career", "reports",
                      "negotiations", "users"):
        assert not autorise("RECRUTEUR", ressource, "read"), ressource
    # Il consulte le catalogue, il ne l'écrit pas.
    assert not autorise("RECRUTEUR", "jobs", "write")
    assert not autorise("RECRUTEUR", "jobs", "delete")


def test_le_rh_herite_du_recruteur():
    """L'héritage évite de répéter la politique : ce que peut le recruteur,
    le RH le peut aussi, sans qu'aucune ligne ne le redise."""
    assert autorise("RH", "scoring", "write")
    assert autorise("RH", "interviews", "write")
    # Et il ajoute son propre périmètre.
    assert autorise("RH", "budget", "write")
    assert autorise("RH", "jobs", "write")


def test_le_rh_ne_gere_pas_les_comptes():
    """La frontière avec l'administrateur : il consulte les fiches, il ne crée
    ni ne supprime de compte."""
    assert autorise("RH", "users", "read")
    assert not autorise("RH", "users", "write")
    assert not autorise("RH", "users", "delete")


def test_le_candidat_n_a_aucune_permission_de_backoffice():
    for ressource in ("jobs", "applications", "scoring", "dashboard", "cv",
                      "interviews", "budget", "users"):
        for action in ("read", "write", "delete"):
            assert not autorise("CANDIDAT", ressource, action), (ressource, action)


def test_un_role_inconnu_n_obtient_rien():
    """Défaut fermé : un rôle absent de la politique — une valeur restée en
    base après une migration ratée, par exemple — ne donne accès à rien."""
    assert not autorise("RH_MANAGER", "jobs", "read")   # ancien nom
    assert not autorise(None, "jobs", "read")
    assert not autorise("", "jobs", "read")


def test_les_permissions_exposees_a_l_interface_suivent_l_heritage():
    perms = permissions_de("RH")
    assert "write" in perms["scoring"]      # hérité du recruteur
    assert "write" in perms["budget"]       # propre au RH
    assert permissions_de("CANDIDAT") == {}


# ── Les trous refermés ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_tableau_de_bord_se_ferme_au_candidat(
    client: AsyncClient, db: AsyncSession
):
    """
    Les KPI agrègent TOUTE la base — volumes de candidatures, score moyen.
    L'endpoint ne demandait qu'un compte connecté.
    """
    resp = await client.get("/api/v1/dashboard/stats",
                            headers=await _compte(client, db, UserRole.CANDIDAT))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_le_tableau_de_bord_reste_ouvert_au_recruteur(
    client: AsyncClient, db: AsyncSession
):
    resp = await client.get("/api/v1/dashboard/stats",
                            headers=await _compte(client, db, UserRole.RECRUTEUR))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_la_negociation_salariale_se_ferme_au_candidat(
    client: AsyncClient, db: AsyncSession
):
    """Un candidat pouvait lancer une négociation et lire les salaires prédits."""
    resp = await client.post(
        "/api/v1/negotiations/predict-salary",
        json={"title": "Développeur", "description": "", "skills_text": "",
              "experience_years": 3},
        headers=await _compte(client, db, UserRole.CANDIDAT),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_le_recruteur_n_accede_pas_au_budget(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/budget/stats",
                            headers=await _compte(client, db, UserRole.RECRUTEUR))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_le_recruteur_ne_gere_pas_les_utilisateurs(
    client: AsyncClient, db: AsyncSession
):
    resp = await client.get("/api/v1/users",
                            headers=await _compte(client, db, UserRole.RECRUTEUR))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_le_rh_consulte_les_utilisateurs_sans_pouvoir_en_creer(
    client: AsyncClient, db: AsyncSession
):
    entete = await _compte(client, db, UserRole.RH)
    assert (await client.get("/api/v1/users", headers=entete)).status_code == 200
    cree = await client.post("/api/v1/users", headers=entete, json={
        "email": "nouveau@example.com", "username": "nouveau",
        "password": VALID_PASSWORD, "full_name": "Nouveau", "role": "CANDIDAT",
    })
    assert cree.status_code == 403


@pytest.mark.asyncio
async def test_chacun_lit_ses_propres_permissions(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/users/me/permissions",
                            headers=await _compte(client, db, UserRole.RECRUTEUR))
    assert resp.status_code == 200
    corps = resp.json()
    assert corps["role"] == "RECRUTEUR"
    assert "write" in corps["permissions"]["scoring"]
    assert "budget" not in corps["permissions"]


# ── Fichiers CV : confinement et propriété ────────────────────────────────────

async def _candidat_avec_cv(db: AsyncSession, tmp_path: Path) -> tuple[User, Path]:
    """Un candidat, son CV sur disque SOUS le répertoire des CV."""
    from app.services import cv_storage

    tag = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(), email=f"cand_{tag}@example.com", username=f"cand_{tag}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat CV",
        role=UserRole.CANDIDAT, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidate = Candidate(id=uuid.uuid4(), user_id=user.id, full_name="Candidat CV")
    job = JobOffer(id=uuid.uuid4(), title="Poste", description="x")
    db.add_all([candidate, job])
    await db.flush()

    fichier = cv_storage.CV_ROOT / f"test_{tag}.pdf"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_bytes(b"%PDF-1.4 contenu de test")
    candidate.cv_path = str(fichier)

    db.add(Application(
        id=uuid.uuid4(), candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path=str(fichier), status="REVIEWED",
    ))
    await db.commit()
    return user, fichier


async def _entete(client: AsyncClient, email: str) -> dict[str, str]:
    jeton = (await client.post("/api/v1/auth/login", json={
        "email": email, "password": VALID_PASSWORD,
    })).json()["access_token"]
    return {"Authorization": f"Bearer {jeton}"}


@pytest.mark.asyncio
async def test_un_candidat_voit_son_propre_cv(client: AsyncClient, db: AsyncSession, tmp_path):
    """L'espace candidat prévisualise le CV déposé : ce chemin doit rester ouvert."""
    user, fichier = await _candidat_avec_cv(db, tmp_path)
    resp = await client.get(f"/api/v1/recruitment/cv-preview/{fichier}",
                            headers=await _entete(client, user.email))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_un_candidat_ne_voit_pas_le_cv_d_un_autre(
    client: AsyncClient, db: AsyncSession, tmp_path
):
    """
    Le trou principal : l'endpoint ne vérifiait que l'authentification. Il
    suffisait de connaître — ou de deviner — le chemin d'un autre CV.
    """
    _, fichier_a = await _candidat_avec_cv(db, tmp_path)
    user_b, _ = await _candidat_avec_cv(db, tmp_path)

    resp = await client.get(f"/api/v1/recruitment/cv-preview/{fichier_a}",
                            headers=await _entete(client, user_b.email))
    # 404 et non 403 : dire « interdit » confirmerait que ce CV existe.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_le_backoffice_consulte_les_cv(client: AsyncClient, db: AsyncSession, tmp_path):
    """Lire les CV est le métier du recruteur : la restriction ne doit pas le gêner."""
    _, fichier = await _candidat_avec_cv(db, tmp_path)
    resp = await client.get(f"/api/v1/recruitment/cv-preview/{fichier}",
                            headers=await _compte(client, db, UserRole.RECRUTEUR))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_aucun_fichier_hors_du_repertoire_des_cv(
    client: AsyncClient, db: AsyncSession, tmp_path
):
    """
    Le paramètre est un `:path` : il acceptait `../../` et `FileResponse`
    servait alors n'importe quel fichier lisible par le processus, CV ou non.

    La traversée est vérifiée ici sur la fonction de résolution elle-même :
    un client HTTP normalise `../../` AVANT l'envoi, si bien qu'un test qui
    passerait par l'URL ne mesurerait que la normalisation du client — pas la
    défense du serveur, qui est ce qu'on veut protéger.
    """
    from fastapi import HTTPException
    from app.api.v1.endpoints.recruitment import _cv_autorise

    admin = User(
        id=uuid.uuid4(), email=f"adm_{uuid.uuid4().hex[:8]}@example.com",
        username=f"adm_{uuid.uuid4().hex[:8]}", hashed_password=hash_password(VALID_PASSWORD),
        full_name="Admin", role=UserRole.ADMIN, is_active=True, is_verified=True,
    )
    db.add(admin)
    await db.commit()

    for chemin in ("../../app/core/config.py",
                   "uploads/cvs/../../app/main.py",
                   "app/core/rbac_policy.csv",
                   str(Path("app/core/rbac_policy.csv").resolve())):
        with pytest.raises(HTTPException) as refus:
            await _cv_autorise(chemin, admin, db)
        assert refus.value.status_code == 404, chemin


@pytest.mark.asyncio
async def test_un_chemin_encode_ne_contourne_pas_le_confinement(
    client: AsyncClient, db: AsyncSession, tmp_path
):
    """Même encodée, la traversée n'atteint rien hors du répertoire des CV."""
    entete = await _compte(client, db, UserRole.ADMIN)
    resp = await client.get(
        "/api/v1/recruitment/cv-preview/uploads/cvs/%2E%2E/%2E%2E/app/main.py",
        headers=entete,
    )
    assert resp.status_code == 404
