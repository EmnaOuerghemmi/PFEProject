"""
Lot 3 — champs employé et fiche à compléter.

Deux décisions que ces tests figent :

1. **On stocke la date de naissance, jamais l'âge.** Un âge écrit en base
   devient faux au bout d'un an et rien ne le signale. Il est donc calculé —
   et le calcul doit tenir compte de l'anniversaire non encore passé, sinon
   toute une génération est vieillie d'un an la moitié de l'année.
2. **Une fiche créée automatiquement doit dire ce qui lui manque.** Elle naît
   à la signature du contrat, sans personne devant l'écran ; sans ce
   signalement, elle resterait à moitié vide indéfiniment — et les
   répartitions par âge et par genre du tableau de bord n'auraient jamais de
   données.
"""
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.employee import EXPECTED_FIELDS, GENDERS, Employee
from app.models.user import User, UserRole
from app.schemas.employee import EmployeeCreate, EmployeeResponse

from tests.conftest import VALID_PASSWORD


def _employe(**champs) -> Employee:
    base = dict(id=uuid.uuid4(), first_name="Amal", last_name="Ben Salah",
                email=f"e_{uuid.uuid4().hex[:8]}@example.com", status="active")
    base.update(champs)
    return Employee(**base)


# ── L'âge se calcule ──────────────────────────────────────────────────────────

def test_lage_se_calcule_depuis_la_date_de_naissance():
    trente_ans = date.today().replace(year=date.today().year - 30)
    assert _employe(birth_date=trente_ans).age == 30


def test_un_anniversaire_non_encore_passe_ne_compte_pas():
    """
    Le piège classique : une simple soustraction d'années vieillit d'un an la
    moitié de l'effectif pendant la moitié de l'année.
    """
    demain = date.today() + timedelta(days=1)
    naissance = demain.replace(year=demain.year - 40)
    assert _employe(birth_date=naissance).age == 39


def test_un_anniversaire_du_jour_compte():
    aujourdhui = date.today()
    naissance = aujourdhui.replace(year=aujourdhui.year - 25)
    assert _employe(birth_date=naissance).age == 25


def test_sans_date_de_naissance_lage_est_absent_pas_zero():
    """
    Zéro placerait tous les employés non renseignés dans la tranche des
    nouveau-nés, et la répartition par âge du tableau de bord serait fausse
    sans que rien ne le montre.
    """
    assert _employe().age is None


def test_lage_nest_pas_une_colonne():
    """S'il le devenait, il vieillirait mal — c'est tout l'objet du choix."""
    colonnes = {c.name for c in Employee.__table__.columns}
    assert "birth_date" in colonnes
    assert "age" not in colonnes


# ── Fiche à compléter ─────────────────────────────────────────────────────────

def test_une_fiche_vide_liste_tout_ce_qui_manque():
    manquants = _employe().missing_fields
    assert set(manquants) == set(EXPECTED_FIELDS)


def test_une_fiche_complete_ne_signale_rien():
    complet = _employe(
        birth_date=date(1990, 5, 12), gender="F", position="Développeuse",
        department="Tech", contract_type="CDI", hire_date=date(2024, 1, 8),
    )
    assert complet.missing_fields == []


def test_non_renseigne_est_une_reponse_pas_un_manque():
    """
    Le RH qui a délibérément choisi « non renseigné » ne doit pas être relancé
    indéfiniment sur ce champ.
    """
    e = _employe(gender="NON_RENSEIGNE")
    assert "gender" not in e.missing_fields


def test_une_chaine_vide_compte_comme_un_manque():
    """Un champ rempli d'espaces n'est pas rempli."""
    assert "department" in _employe(department="   ").missing_fields


# ── Vocabulaire ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("genre", GENDERS)
def test_chaque_genre_du_vocabulaire_est_accepte(genre):
    EmployeeCreate(first_name="A", last_name="B", email="a@b.tn", gender=genre)


def test_un_genre_hors_vocabulaire_est_refuse():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        EmployeeCreate(first_name="A", last_name="B", email="a@b.tn", gender="AUTRECHOSE")


def test_un_type_de_contrat_inconnu_est_refuse():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        EmployeeCreate(first_name="A", last_name="B", email="a@b.tn",
                       contract_type="INTERIM")


def test_le_genre_reste_facultatif():
    """La fiche est créée sans humain : exiger le genre bloquerait l'embauche."""
    EmployeeCreate(first_name="A", last_name="B", email="a@b.tn")


# ── Sérialisation ─────────────────────────────────────────────────────────────

def test_la_reponse_porte_lage_et_les_manques_en_camelcase():
    e = _employe(birth_date=date(1990, 3, 4), gender="M", position="Dev")
    charge = EmployeeResponse.model_validate(e).model_dump(by_alias=True)
    assert charge["age"] == _employe(birth_date=date(1990, 3, 4)).age
    assert "missingFields" in charge
    assert "birthDate" in charge


# ── Bout en bout ──────────────────────────────────────────────────────────────

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


@pytest.mark.asyncio
async def test_lapi_cree_un_employe_avec_ses_donnees_rh(
    client: AsyncClient, db: AsyncSession
):
    entete = await _entete_rh(client, db)
    resp = await client.post("/api/v1/employees", headers=entete, json={
        "firstName": "Nour", "lastName": "Trabelsi",
        "email": f"n_{uuid.uuid4().hex[:8]}@example.com",
        "birthDate": "1992-07-19", "gender": "F",
        "contractType": "CDI", "position": "Data Engineer",
        "department": "Data", "hireDate": "2025-03-01T00:00:00Z",
    })
    assert resp.status_code in (200, 201), resp.text
    corps = resp.json()
    assert corps["gender"] == "F"
    assert corps["age"] is not None
    assert corps["missingFields"] == []


@pytest.mark.asyncio
async def test_lapi_refuse_un_genre_invente(client: AsyncClient, db: AsyncSession):
    entete = await _entete_rh(client, db)
    resp = await client.post("/api/v1/employees", headers=entete, json={
        "firstName": "Nour", "lastName": "Trabelsi",
        "email": f"n_{uuid.uuid4().hex[:8]}@example.com",
        "gender": "INVENTE",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_une_fiche_partielle_annonce_ce_qui_manque(
    client: AsyncClient, db: AsyncSession
):
    """C'est l'état dans lequel naissent les fiches créées automatiquement."""
    entete = await _entete_rh(client, db)
    resp = await client.post("/api/v1/employees", headers=entete, json={
        "firstName": "Sami", "lastName": "Khelifi",
        "email": f"s_{uuid.uuid4().hex[:8]}@example.com",
    })
    assert resp.status_code in (200, 201), resp.text
    manquants = resp.json()["missingFields"]
    assert "birth_date" in manquants
    assert "gender" in manquants
