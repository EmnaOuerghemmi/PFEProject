import os

# Backend d'embedding déterministe et hors-ligne pour les tests : le hash
# fallback évite le téléchargement du modèle sentence-transformers (~470 Mo)
# et rend les similarités reproductibles. À poser AVANT l'import de l'app.
os.environ.setdefault("EMBEDDINGS_BACKEND", "hash")

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Base de test : un fichier par PROCESSUS pytest.
#
# Avec un nom fixe, deux exécutions concurrentes — ou un processus résiduel qui
# garde le fichier ouvert — se disputent le même SQLite et produisent des
# « no such table » ou des « database is locked » qui n'ont rien à voir avec le
# code testé. Le PID isole chaque exécution ; `TEST_DB_PATH` permet de forcer
# un chemin en CI.
import os as _os

TEST_DB_PATH = _os.environ.get("TEST_DB_PATH") or f"./test_{_os.getpid()}.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# NullPool : pytest-asyncio (>=1.x) exécute chaque test dans son propre event
# loop ; des connexions poolées créées sur la loop d'un test précédent
# provoqueraient « RuntimeError: Event loop is closed ».
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session", autouse=True)
def _aucun_email_reel():
    """
    Coupe l'envoi d'e-mails pour TOUTE la session de test.

    Sans ce garde-fou, `pytest` lancé sur une machine où `SMTP_HOST` et
    `SMTP_USER` sont renseignés — le cas du poste de développement — envoie de
    VRAIS messages : le service ne retombe en mode journal que lorsque le SMTP
    n'est pas configuré. Les comptes de test étant en `@example.com`, domaine
    réservé qui ne reçoit rien (RFC 2606), chaque exécution renvoyait une volée
    d'avis de non-remise dans la boîte d'expédition.

    On coupe au plus bas niveau, `_send_sync` : tous les gabarits passent par
    lui, donc aucun n'échappe au filet, et les tests qui remplacent un
    `send_*` précis pour vérifier ses arguments continuent de fonctionner.

    Remplacer les adresses de test par de vraies adresses aggraverait les
    choses — les avis de non-remise deviendraient de vrais messages, en
    nombre, à chaque exécution.
    """
    import app.services.email_service as email_service

    envoyes: list[tuple[str, str]] = []

    def _capture(to_email, subject, html, attachments=None):
        envoyes.append((to_email, subject))
        return True

    origine = email_service._send_sync
    email_service._send_sync = _capture
    try:
        yield envoyes
    finally:
        email_service._send_sync = origine


@pytest_asyncio.fixture(autouse=True)
async def _fresh_redis():
    """
    Le client Redis global se lie à l'event loop qui l'a créé. Comme chaque
    test tourne dans sa propre loop, on repart d'un client neuf par test
    (sinon : « Event loop is closed » dès le 2e login de la session).

    On purge aussi les compteurs de limitation, qui vivent dans le VRAI Redis
    avec des TTL longs et fuiteraient donc d'une exécution de tests à l'autre :
      - `login_attempts:*` : anti-bruteforce du login (TTL 15 min)
      - `ratelimit:*`      : limitation de register / forgot-password / jetons
                             (TTL jusqu'à 1 h). Sans cette purge, une poignée
                             de tests qui enregistrent un compte épuisent le
                             quota (10/h) et tous les suivants reçoivent 429.
    """
    from app.cache import redis_client
    redis_client._redis = None
    try:
        r = await redis_client.get_redis()
        keys = await r.keys("login_attempts:*") + await r.keys("ratelimit:*")
        if keys:
            await r.delete(*keys)
    except Exception:
        redis_client._redis = None
    yield
    try:
        await redis_client.close_redis()
    except Exception:
        redis_client._redis = None


@pytest_asyncio.fixture(scope="function")
async def db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionLocal() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db: AsyncSession):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


VALID_PASSWORD = "Test1234!"
WEAK_PASSWORD = "weak"
# Identifiants d'un superadmin RÉEL, pour les rares tests qui veulent
# s'authentifier contre un environnement déjà peuplé. Ils viennent de
# l'environnement, jamais du dépôt : celui-ci est distant, et un mot de passe
# d'administrateur poussé sur une forge y reste lisible même après
# suppression du fichier. Absents, les tests concernés se contentent de passer
# leur tour (`pytest.skip`).
SUPERADMIN_EMAIL = _os.environ.get("TEST_SUPERADMIN_EMAIL", "")
SUPERADMIN_PASSWORD = _os.environ.get("TEST_SUPERADMIN_PASSWORD", "")

USER_PAYLOAD = {
    "email": "testuser@example.com",
    "username": "testuser",
    "password": VALID_PASSWORD,
    "full_name": "Test User",
}


def pytest_sessionfinish(session, exitstatus):
    """
    Supprime la base de cette exécution.

    Sans ce nettoyage, l'isolation par PID laisserait un fichier `test_<pid>.db`
    derrière chaque lancement. On ignore l'échec : sous Windows, le fichier peut
    rester verrouillé un instant après la fermeture du moteur, et une exception
    ici masquerait le vrai résultat des tests.
    """
    import contextlib
    import os

    with contextlib.suppress(OSError):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
