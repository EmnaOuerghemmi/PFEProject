"""
Sondes de santé : vivant (/health) et prêt (/health/ready).

« Prêt » conditionne la mise en ligne d'une version (deploy/deploy.sh) : il
doit refuser un schéma en retard (migrations non appliquées), mais accepter un
schéma en avance — c'est le cas d'un retour arrière vers l'image précédente.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.health import _scripts


@pytest_asyncio.fixture
async def poser_revision(db: AsyncSession):
    """Pose la révision Alembic de la base ; la table est retirée après le test.

    `alembic_version` n'appartient pas aux modèles : le nettoyage commun
    (`drop_all`) ne la supprime pas, elle fuirait vers le test suivant.
    """
    async def _poser(revision: str | None) -> None:
        await db.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await db.execute(text("DELETE FROM alembic_version"))
        if revision is not None:
            await db.execute(text("INSERT INTO alembic_version (version_num) VALUES (:r)"), {"r": revision})
        await db.commit()

    await db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await db.commit()
    yield _poser
    await db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await db.commit()


@pytest.mark.asyncio
async def test_vivant_ne_depend_de_rien(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_pret_quand_le_schema_est_a_jour(client: AsyncClient, poser_revision):
    await poser_revision(_scripts().get_current_head())

    resp = await client.get("/health/ready")

    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["status"] == "ok"
    assert corps["checks"]["database"] == "ok"
    assert corps["checks"]["redis"] == "ok"
    assert corps["checks"]["schema"]["etat"] == "a_jour"


@pytest.mark.asyncio
async def test_pas_pret_sans_table_de_migrations(client: AsyncClient, poser_revision):
    resp = await client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["status"] == "indisponible"


@pytest.mark.asyncio
async def test_pas_pret_quand_des_migrations_manquent(client: AsyncClient, poser_revision):
    tete = _scripts().get_revision(_scripts().get_current_head())
    await poser_revision(tete.down_revision)

    resp = await client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["schema"]["etat"] == "en_retard"


@pytest.mark.asyncio
async def test_pret_apres_un_retour_arriere(client: AsyncClient, poser_revision):
    # Une version plus récente a migré la base, puis on est revenu à celle-ci.
    await poser_revision("revision_future_inconnue")

    resp = await client.get("/health/ready")

    assert resp.status_code == 200, resp.text
    assert resp.json()["checks"]["schema"]["etat"] == "en_avance"


@pytest.mark.asyncio
async def test_aucune_erreur_detaillee_n_est_exposee(client: AsyncClient):
    corps = (await client.get("/health/ready")).json()
    # Ni URL de base, ni mot de passe, ni trace : seulement des états.
    assert "postgresql" not in str(corps).lower()
    assert "Traceback" not in str(corps)
