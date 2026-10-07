"""
Lots 4 et 5 — séries de graphiques et tableau de bord composable.

Deux garanties, et la seconde n'est pas une politesse :

1. **Aucune source n'offre un type qui ment sur sa donnée.** Un camembert de
   série temporelle détruirait l'axe du temps, qui est toute l'information ; une
   courbe reliant des statuts relierait des points entre lesquels il n'y a rien.
   La règle vit côté serveur et voyage avec la série.
2. **Aucune tranche démographique trop petite n'est publiée.** Un « genre ×
   service » dans un service de trois personnes ne montre pas une statistique,
   il montre trois personnes que n'importe quel collègue reconnaîtra. C'est ce
   qui sépare une répartition d'un trombinoscope.
"""
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.schemas.analytics import ALLOWED_TYPES, ChartType, SeriesKind
from app.services.chart_series_service import (
    SEUIL_ANONYMAT, chart_series_service as svc,
)

from tests.conftest import VALID_PASSWORD


async def _employes(db: AsyncSession, combien: int, **champs) -> None:
    for _ in range(combien):
        db.add(Employee(
            id=uuid.uuid4(), first_name="Test", last_name="Employé",
            email=f"e_{uuid.uuid4().hex[:10]}@example.com", status="active",
            **champs,
        ))
    await db.commit()


def _ne_de_il_y_a(annees: int) -> date:
    aujourdhui = date.today()
    return aujourdhui.replace(year=aujourdhui.year - annees) - timedelta(days=1)


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


# ── Le catalogue et ses règles ────────────────────────────────────────────────

def test_les_cinq_types_demandes_sont_couverts():
    tous = {t for types in ALLOWED_TYPES.values() for t in types}
    assert tous == set(ChartType)


def test_aucune_serie_temporelle_nadmet_un_camembert():
    """Un camembert détruirait l'axe du temps, qui est toute l'information."""
    assert ChartType.PIE not in ALLOWED_TYPES[SeriesKind.TEMPORELLE]


def test_aucune_serie_categorielle_nadmet_une_courbe():
    """Relier des statuts entre eux relierait des points sans relation."""
    assert ChartType.LINE not in ALLOWED_TYPES[SeriesKind.CATEGORIELLE]


def test_le_nuage_de_points_exige_deux_dimensions_numeriques():
    for nature, types in ALLOWED_TYPES.items():
        if ChartType.SCATTER in types:
            assert nature == SeriesKind.NUMERIQUE_2D


def test_chaque_source_du_catalogue_est_coherente():
    for source in svc.catalog().sources:
        assert source.allowed_types == ALLOWED_TYPES[source.kind], source.id
        assert source.default_type in source.allowed_types, source.id
        assert source.description, source.id


def test_le_catalogue_couvre_le_recrutement_et_leffectif():
    categories = {s.category for s in svc.catalog().sources}
    assert {"Recrutement", "Candidats", "Effectif"} <= categories


# ── Anonymat ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_tranche_trop_petite_est_regroupee(db: AsyncSession):
    """Sous le seuil, une tranche désigne des personnes, pas une statistique."""
    await _employes(db, SEUIL_ANONYMAT + 2, gender="F")
    await _employes(db, 2, gender="M")            # sous le seuil

    serie = await svc.series(db, "employees_by_gender")
    libelles = {p.label: p.y for p in serie.points}

    assert "Homme" not in libelles, "une tranche de 2 ne doit pas être publiée"
    assert libelles.get("Autres") == 2.0
    assert libelles["Femme"] == float(SEUIL_ANONYMAT + 2)


@pytest.mark.asyncio
async def test_non_renseigne_echappe_au_regroupement(db: AsyncSession):
    """
    Ce n'est pas une catégorie de personnes mais une mesure du travail restant.
    La masquer reviendrait à cacher combien de fiches sont à compléter.
    """
    await _employes(db, SEUIL_ANONYMAT + 1, gender="F")
    await _employes(db, 2)                        # sans genre

    serie = await svc.series(db, "employees_by_gender")
    libelles = {p.label: p.y for p in serie.points}
    assert libelles.get("Non renseigné") == 2.0


@pytest.mark.asyncio
async def test_le_nuage_age_salaire_ne_publie_rien_sous_le_seuil(db: AsyncSession):
    """
    Chaque point EST une personne. Sous le seuil, la série n'est pas publiée du
    tout — un nuage de quatre points est un annuaire.
    """
    await _employes(db, 3, birth_date=_ne_de_il_y_a(30), salary=2000.0)
    serie = await svc.series(db, "employees_age_salary")
    assert serie.points == []


@pytest.mark.asyncio
async def test_le_nuage_arrondit_les_salaires(db: AsyncSession):
    """Un salaire exact identifie son porteur aussi sûrement qu'un nom."""
    await _employes(db, SEUIL_ANONYMAT + 1,
                    birth_date=_ne_de_il_y_a(33), salary=2347.0)
    serie = await svc.series(db, "employees_age_salary")
    assert serie.points, "au-dessus du seuil, la série doit exister"
    for point in serie.points:
        assert point.y % 100 == 0, f"{point.y} n'est pas arrondi à la centaine"


# ── Répartition par âge ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_employe_sans_date_de_naissance_ne_tombe_pas_dans_une_tranche(
    db: AsyncSession
):
    """
    Sinon toute la population non renseignée atterrirait chez les nouveau-nés,
    et la répartition serait fausse sans que rien ne le montre.
    """
    await _employes(db, SEUIL_ANONYMAT + 1)       # aucune date de naissance

    serie = await svc.series(db, "employees_by_age")
    libelles = {p.label for p in serie.points}
    assert "Non renseigné" in libelles
    assert "Moins de 25 ans" not in libelles


@pytest.mark.asyncio
async def test_les_tranches_dage_sont_ordonnees(db: AsyncSession):
    """La nature ORDONNEE n'a de sens que si l'ordre est respecté."""
    await _employes(db, SEUIL_ANONYMAT + 1, birth_date=_ne_de_il_y_a(22))
    await _employes(db, SEUIL_ANONYMAT + 1, birth_date=_ne_de_il_y_a(40))

    serie = await svc.series(db, "employees_by_age")
    libelles = [p.label for p in serie.points]
    assert libelles.index("Moins de 25 ans") < libelles.index("35–44 ans")


# ── Format commun ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_toutes_les_sources_rendent_le_meme_format(db: AsyncSession):
    """
    C'est le pivot de tout le lot : sans forme commune, aucun sélecteur de type
    ne peut fonctionner.
    """
    for descripteur in svc.catalog().sources:
        serie = await svc.series(db, descripteur.id)
        assert serie is not None, descripteur.id
        assert serie.allowed_types == descripteur.allowed_types
        for point in serie.points:
            assert isinstance(point.label, str)
            assert isinstance(point.y, float)


@pytest.mark.asyncio
async def test_une_source_inconnue_rend_none(db: AsyncSession):
    assert await svc.series(db, "source_inventee") is None


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lapi_sert_le_catalogue(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/reports/series",
                            headers=await _entete_rh(client, db))
    assert resp.status_code == 200, resp.text
    sources = resp.json()["sources"]
    assert len(sources) >= 10
    assert all("allowed_types" in s for s in sources)


@pytest.mark.asyncio
async def test_lapi_refuse_une_source_inconnue(client: AsyncClient, db: AsyncSession):
    resp = await client.get("/api/v1/reports/series/inventee",
                            headers=await _entete_rh(client, db))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_le_catalogue_est_reserve_au_backoffice(client: AsyncClient):
    assert (await client.get("/api/v1/reports/series")).status_code in (401, 403)


# ── Composition commune du tableau de bord ────────────────────────────────────

async def _entete(client: AsyncClient, db: AsyncSession, role: str) -> dict[str, str]:
    email = f"{role.lower()}_{uuid.uuid4().hex[:6]}@exemple.tn"
    db.add(User(id=uuid.uuid4(), email=email, username=email.split("@")[0],
                hashed_password=hash_password(VALID_PASSWORD), full_name=role,
                role=role, is_active=True, is_verified=True))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _graphique(gid: str, source: str, visible_to: str = "ALL") -> dict:
    return {"id": gid, "source_id": source, "chart_type": "pie",
            "title": None, "span": 6, "visible_to": visible_to}


@pytest.mark.asyncio
async def test_une_composition_survit_a_la_deconnexion(
    client: AsyncClient, db: AsyncSession
):
    entete = await _entete_rh(client, db)
    composition = {
        "charts": [{"id": "c1", "source_id": "employees_by_gender",
                    "chart_type": "pie", "title": "Mon camembert", "span": 6}],
        "customized": True,
    }
    resp = await client.put("/api/v1/dashboard/config", headers=entete, json=composition)
    assert resp.status_code == 200, resp.text

    relu = await client.get("/api/v1/dashboard/config", headers=entete)
    assert relu.status_code == 200
    charts = relu.json()["charts"]
    assert len(charts) == 1
    assert charts[0]["title"] == "Mon camembert"
    assert charts[0]["visible_to"] == "ALL"          # audience par défaut
    assert relu.json()["can_edit"] is True


@pytest.mark.asyncio
async def test_une_source_disparue_est_ecartee_a_lenregistrement(
    client: AsyncClient, db: AsyncSession
):
    """
    Plutôt qu'à l'affichage : une source retirée du catalogue ne doit pas
    casser le tableau de bord des mois plus tard.
    """
    entete = await _entete_rh(client, db)
    resp = await client.put("/api/v1/dashboard/config", headers=entete, json={
        "charts": [_graphique("c1", "employees_by_gender"),
                   _graphique("c2", "source_qui_nexiste_plus")],
        "customized": True,
    })
    assert resp.status_code == 200, resp.text
    gardes = [c["source_id"] for c in resp.json()["charts"]]
    assert gardes == ["employees_by_gender"]


@pytest.mark.asyncio
async def test_un_tableau_vide_reste_vide(client: AsyncClient, db: AsyncSession):
    """
    `customized` distingue « jamais personnalisé » de « vidé volontairement ».
    Sans cette distinction, retirer le dernier graphique ferait réapparaître la
    composition d'origine — et on ne pourrait jamais vider le tableau.
    """
    entete = await _entete_rh(client, db)
    await client.put("/api/v1/dashboard/config", headers=entete,
                     json={"charts": [], "customized": True})
    relu = (await client.get("/api/v1/dashboard/config", headers=entete)).json()
    assert relu["charts"] == []
    assert relu["customized"] is True


# ── Qui voit quoi ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seul_l_admin_modifie_la_composition(client: AsyncClient, db: AsyncSession):
    for role in ("RH", "RECRUTEUR"):
        entete = await _entete(client, db, role)
        resp = await client.put("/api/v1/dashboard/config", headers=entete,
                                json={"charts": [], "customized": True})
        assert resp.status_code == 403, role
        assert (await client.get("/api/v1/dashboard/config", headers=entete)).json()["can_edit"] is False
        # Le catalogue ne sert qu'à créer un graphique : réservé à l'admin.
        assert (await client.get("/api/v1/dashboard/series", headers=entete)).status_code == 403


@pytest.mark.asyncio
async def test_chaque_role_ne_recoit_que_ses_graphiques(client: AsyncClient, db: AsyncSession):
    admin = await _entete_rh(client, db)
    await client.put("/api/v1/dashboard/config", headers=admin, json={
        "charts": [_graphique("tous", "employees_by_gender", "ALL"),
                   _graphique("rh", "employees_by_gender", "RH"),
                   _graphique("rec", "employees_by_gender", "RECRUTEUR"),
                   _graphique("adm", "employees_by_gender", "ADMIN")],
        "customized": True,
        "builtin_visibility": {"evolution": "RH", "education": "ADMIN"},
    })

    def ids(cfg):
        return sorted(c["id"] for c in cfg["charts"])

    rh = (await client.get("/api/v1/dashboard/config", headers=await _entete(client, db, "RH"))).json()
    assert ids(rh) == ["rh", "tous"]
    assert "evolution" in rh["builtin_visibility"] and "education" not in rh["builtin_visibility"]

    rec = (await client.get("/api/v1/dashboard/config", headers=await _entete(client, db, "RECRUTEUR"))).json()
    assert ids(rec) == ["rec", "tous"]
    assert "evolution" not in rec["builtin_visibility"]
    assert "status" in rec["builtin_visibility"]       # carte non réglée = tous

    tout = (await client.get("/api/v1/dashboard/config", headers=admin)).json()
    assert ids(tout) == ["adm", "rec", "rh", "tous"]


@pytest.mark.asyncio
async def test_les_donnees_suivent_la_visibilite(client: AsyncClient, db: AsyncSession):
    """Masquer à l'écran ne suffit pas : l'API refuse aussi les données."""
    admin = await _entete_rh(client, db)
    await client.put("/api/v1/dashboard/config", headers=admin, json={
        "charts": [_graphique("rh", "employees_by_gender", "RH")],
        "customized": True,
        "builtin_visibility": {"evolution": "ADMIN"},
    })
    rh = await _entete(client, db, "RH")
    rec = await _entete(client, db, "RECRUTEUR")

    assert (await client.get("/api/v1/dashboard/series/employees_by_gender", headers=rh)).status_code == 200
    assert (await client.get("/api/v1/dashboard/series/employees_by_gender", headers=rec)).status_code == 403
    assert (await client.get("/api/v1/dashboard/applications-timeline", headers=rh)).status_code == 403
    # Statuts, offres, pipeline, performance : non réglés, donc visibles de tous.
    assert (await client.get("/api/v1/dashboard/recruitment-summary", headers=rec)).status_code == 200


@pytest.mark.asyncio
async def test_audience_hors_vocabulaire_refusee(client: AsyncClient, db: AsyncSession):
    admin = await _entete_rh(client, db)
    resp = await client.put("/api/v1/dashboard/config", headers=admin, json={
        "charts": [_graphique("x", "employees_by_gender", "CANDIDAT")], "customized": True,
    })
    assert resp.status_code == 422
