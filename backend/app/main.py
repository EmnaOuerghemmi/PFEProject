import logging
from contextlib import asynccontextmanager

import os

from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings as _settings

# Uvicorn ne configure QUE ses propres loggers (`uvicorn`, `uvicorn.error`,
# `uvicorn.access`) et laisse le logger racine à WARNING. Sans cet appel, tous
# les `logger.info` de l'application — modèle ML chargé, e-mails envoyés,
# entretiens synchronisés — sont silencieusement jetés, en local comme en
# conteneur. `basicConfig` ne touche pas aux loggers d'uvicorn (leur
# `propagate` est à False), il n'y a donc pas de double affichage.
logging.basicConfig(
    level=getattr(logging, _settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# Alembic annonce le chargement de chacun de ses plugins d'autogénération à
# chaque démarrage : six lignes sans valeur opérationnelle, qui noieraient les
# messages utiles. Ses avertissements et erreurs restent visibles.
logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)

from app.api.v1.router import api_router
from app.cache.redis_client import close_redis, get_redis
from app.core.config import settings
from app.db.session import engine, AsyncSessionLocal, get_db
from app.db.init_db import init_superadmin
# Peuple Base.metadata avec l'ensemble des tables (cf. app/models/__init__.py).
# Remplace la liste d'imports manuelle qui omettait `agent_log`.
import app.models  # noqa: F401

# Les identifiants du superadmin viennent de l'environnement (cf. Settings) :
# en dur dans ce fichier, ils étaient committés — donc publics — dans Git.
# Sans SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD, le compte n'est pas créé.


async def _verify_schema_is_current(log) -> None:
    """
    Vérifie que la base porte bien la dernière révision Alembic.

    Ne modifie jamais le schéma : en cas d'écart, on journalise une erreur
    explicite plutôt que de « réparer » silencieusement, ce que faisait
    l'ancien `create_all` (source de dérives entre environnements).
    """
    from app.core.health import A_JOUR, EN_AVANCE, etat_du_schema
    try:
        async with engine.connect() as conn:
            etat, current, head = await etat_du_schema(conn)

        if etat == A_JOUR:
            log.info(f"Schéma à jour (révision Alembic {current}).")
        elif etat == EN_AVANCE:
            log.warning(
                f"Base en avance sur ce code ('{current}', code en '{head}') : "
                f"retour à une version précédente. Sans risque si les migrations "
                f"récentes sont rétrocompatibles."
            )
        else:
            log.error(
                f"SCHÉMA DÉSYNCHRONISÉ — base en '{current}', code en '{head}'. "
                f"Lancer : alembic upgrade head"
            )
    except Exception as exc:  # pragma: no cover - SQLite/tests, ou table absente
        log.warning(
            f"Contrôle de schéma impossible ({exc}). "
            f"Si la base est vide, lancer : alembic upgrade head"
        )


async def _interview_expiry_loop():
    """Sweep expired interview invitations every 5 minutes."""
    import asyncio
    from app.services.interview_service import interview_service
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await interview_service.sweep_expired(db)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Interview expiry sweep failed: {exc}")
        await asyncio.sleep(300)  # 5 minutes


async def _assessment_expiry_loop():
    """
    Clôt les tests techniques dont le temps est écoulé, toutes les 2 minutes.

    Sans ce balayage, un candidat qui ferme son navigateur en cours de test
    laisserait sa session EN_COURS indéfiniment : elle n'apparaîtrait jamais
    comme terminée côté RH, et ne serait jamais corrigée.
    """
    import asyncio
    from app.services.assessment_service import (
        send_due_test_notifications, sweep_expired_sessions,
    )
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await sweep_expired_sessions(db)
                # Dans le même tour : une session que la clôture ci-dessus
                # vient de fermer doit être annoncée maintenant, pas au tour
                # suivant. Le RH attend cette alerte pour enchaîner.
                await send_due_test_notifications(db)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Assessment expiry sweep failed: {exc}")
        await asyncio.sleep(120)


async def _interview_meet_reminder_loop():
    """
    Envoie le rappel « rejoindre maintenant » des entretiens confirmés qui
    commencent dans les prochaines minutes (INTERVIEW_MEET_REMINDER_MINUTES),
    au candidat + RH + superadmin.

    Sondage toutes les 60 s : le rappel part dans la minute qui suit le seuil.
    Une seule requête indexée par minute — coût négligeable.
    """
    import asyncio
    from app.services.interview_service import interview_service
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await interview_service.send_due_meet_reminders(db)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Interview meet reminder loop failed: {exc}")
        await asyncio.sleep(60)


async def _talent_pool_loop():
    """
    Invite les candidats en réserve sur les offres qui correspondent à leur
    profil (voir `talent_pool_service`). Premier passage après quelques
    minutes : les modèles et l'index sémantique se chargent au démarrage.
    """
    import asyncio
    from app.core.config import settings as _settings
    from app.services.talent_pool_service import inviter_sur_offres_compatibles
    await asyncio.sleep(180)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await inviter_sur_offres_compatibles(db)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Talent pool sweep failed: {type(exc).__name__}")
        await asyncio.sleep(max(_settings.TALENT_POOL_SWEEP_MINUTES, 5) * 60)


async def _warmup_models(log) -> None:
    """Charge les modèles ML hors du chemin des requêtes. Jamais bloquant."""
    import asyncio

    async def _charger(nom: str, fn) -> None:
        try:
            debut = asyncio.get_running_loop().time()
            await asyncio.to_thread(fn)
            duree = asyncio.get_running_loop().time() - debut
            log.info(f"Modèle « {nom} » prêt ({duree:.1f}s).")
        except Exception as exc:  # pragma: no cover - dégradation gracieuse
            log.warning(f"Préchauffage de « {nom} » ignoré : {exc}")

    def _salaire() -> None:
        from app.services.salary_prediction_service import get_salary_service
        get_salary_service()

    def _embeddings() -> None:
        from app.services.embedding_service import embedding_service
        embedding_service.embed("préchauffage")

    await _charger("prédiction salariale", _salaire)
    await _charger("embeddings", _embeddings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import logging

    _log = logging.getLogger(__name__)
    await get_redis()

    # ─── Schéma ────────────────────────────────────────────────────────────
    # Le schéma est désormais géré exclusivement par Alembic (`alembic upgrade
    # head`, lancé au démarrage du conteneur). L'application ne crée ni ne
    # modifie plus de table elle-même : on se contente de vérifier que la base
    # est à jour et d'avertir clairement sinon.
    #
    # NB : les tests utilisent SQLite et créent leur schéma via une fixture
    # dédiée (`tests/conftest.py`), ils ne passent pas par ce contrôle.
    await _verify_schema_is_current(_log)

    # pgvector : la colonne `vec` et son index HNSW sont créés par la migration
    # Alembic dédiée, si l'extension est disponible. Ici on ne fait que
    # DÉTECTER le résultat pour aiguiller le service sémantique entre recherche
    # vectorielle native et repli Python — aucun DDL.
    try:
        from sqlalchemy import text
        from app.services.semantic_service import semantic_service
        async with engine.connect() as conn:
            has_vec = await conn.scalar(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='embeddings' AND column_name='vec'"
            ))
        if has_vec:
            semantic_service.pgvector_enabled = True
            _log.info("pgvector actif — recherche sémantique via index vectoriel natif")
        else:
            _log.info("pgvector absent — recherche sémantique en repli Python (cosinus)")
    except Exception as _vec_exc:  # pragma: no cover - SQLite/tests
        _log.debug(f"Détection pgvector ignorée : {_vec_exc}")
    async with AsyncSessionLocal() as db:
        await init_superadmin(
            db,
            settings.SUPERADMIN_EMAIL,
            settings.SUPERADMIN_USERNAME,
            settings.SUPERADMIN_PASSWORD,
        )
    # Seed de démo Budget/Employés (idempotent) pour que le backoffice affiche
    # des données dès le premier lancement.
    try:
        from app.services.budget_service import budget_service
        from app.services.employee_service import employee_service
        from app.services.cag_service import cag_service
        async with AsyncSessionLocal() as db:
            await employee_service.seed_demo_data(db)
            await budget_service.seed_demo_data(db)
            # Base de connaissances CAG : seed de la FAQ uniquement. L'indexation
            # (cache d'embeddings) est PARESSEUSE — faite au 1er /cag/ask — pour
            # ne pas charger le modèle neuronal (~470 Mo) au démarrage.
            await cag_service.seed_default_kb(db)
            await db.commit()
    except Exception as _seed_exc:  # pragma: no cover - demo data must never block boot
        import logging
        logging.getLogger(__name__).warning(f"Demo seed skipped: {_seed_exc}")
    # ─── Préchauffage des modèles ──────────────────────────────────────────
    # Le premier appel à un modèle paie son chargement : ~2,5 s pour le pickle
    # de prédiction salariale, jusqu'à ~120 s pour sentence-transformers
    # (téléchargement compris). Cette facture tombait sur le premier
    # utilisateur, qui voyait son bouton figé sans comprendre.
    #
    # On la règle au démarrage, dans un thread : `create_task` seul ne
    # suffirait pas, ces chargements sont synchrones et figeraient la boucle.
    # Le boot n'attend rien — l'API répond pendant que les modèles chargent.
    warmup_task = asyncio.create_task(_warmup_models(_log))

    expiry_task = asyncio.create_task(_interview_expiry_loop())
    meet_reminder_task = asyncio.create_task(_interview_meet_reminder_loop())
    assessment_task = asyncio.create_task(_assessment_expiry_loop())
    talent_pool_task = asyncio.create_task(_talent_pool_loop())
    yield
    talent_pool_task.cancel()
    expiry_task.cancel()
    meet_reminder_task.cancel()
    assessment_task.cancel()
    warmup_task.cancel()
    # Le SDK Langfuse met les traces en file et les envoie par lots depuis un
    # fil de fond. Sans vidage explicite à l'arrêt, les dernières traces d'un
    # redémarrage sont perdues — précisément celles qui documentent ce qui
    # précédait l'arrêt. Ne lève jamais.
    from app.observability.langfuse_client import langfuse_client
    langfuse_client.shutdown()
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ─── CORS ──────────────────────────────────────────────────────────────────
# Les origines viennent de la configuration (ALLOWED_ORIGINS), plus jamais du
# code : un déploiement se fait en renseignant la variable d'environnement,
# sans toucher aux sources.
#   ALLOWED_ORIGINS=https://app.piqbit.tn,https://admin.piqbit.tn
#   ALLOW_LOCALHOST_ORIGINS=false        # <- impératif en production
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    # Développement uniquement : tolère n'importe quel port localhost
    # (previews Angular, second `ng serve`). Désactivé en production.
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1):\d+"
        if settings.ALLOW_LOCALHOST_ORIGINS
        else None
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response

_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
os.makedirs(os.path.join(_static_dir, "avatars"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

app.include_router(api_router, prefix="/api/v1")

# Negotiations router carries its own /api/v1/negotiations prefix (+ WebSocket),
# so it is mounted directly rather than under api_router. It pulls in the
# salary-prediction stack (numpy/pandas); guard the import so the core ATS API
# still boots if those optional ML deps are absent.
try:
    from app.api.v1.endpoints import negotiations
    app.include_router(negotiations.router)
except Exception as _exc:  # pragma: no cover - optional dependency guard
    import logging
    logging.getLogger(__name__).warning(
        f"Negotiations module not mounted (optional ML deps missing?): {_exc}"
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Vivant : le processus répond (HEALTHCHECK Docker). Voir app/core/health.py."""
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/health/ready", tags=["Health"])
async def readiness_check(db: Annotated[AsyncSession, Depends(get_db)]):
    """Prêt : base, schéma et Redis. 503 tant qu'une condition manque (déploiement, supervision)."""
    from fastapi.responses import JSONResponse
    from app.core.health import verifier_disponibilite

    pret, controles = await verifier_disponibilite(db)
    return JSONResponse(
        status_code=200 if pret else 503,
        content={"status": "ok" if pret else "indisponible", "version": settings.APP_VERSION,
                 "checks": controles},
    )


@app.options("/{full_path:path}")
async def preflight(full_path: str):
    return {}
