"""
Tests du matching sémantique (embeddings + pgvector, V1.6).

En environnement de test : backend d'embedding « hash-v1 » (déterministe,
hors-ligne — forcé dans conftest) et fallback Python pour la similarité
(pas de pgvector sur SQLite). Couvre :
  - le service d'embedding (normalisation, similarité, discrimination)
  - l'indexation offre/CV et l'upsert (pas de doublon)
  - le matching CV↔offre : le bon profil sort premier
  - la recherche de candidats similaires (exclusion de soi-même)
  - l'API bout-en-bout + RBAC
"""
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.recruitment import JobOffer, Candidate, Application
from app.models.scoring import CVAnalysis
from app.models.embedding import Embedding
from app.services.embedding_service import embedding_service
from app.services.semantic_service import semantic_service
from tests.conftest import VALID_PASSWORD


# ── Service d'embedding ───────────────────────────────────────────────────────

def test_embedding_is_normalized_and_deterministic():
    v1 = embedding_service.embed("Développeur Python backend FastAPI")
    v2 = embedding_service.embed("Développeur Python backend FastAPI")
    assert len(v1) == embedding_service.dim
    assert v1 == v2  # déterministe
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6  # L2-normalisé


def test_embedding_discriminates_topics():
    frontend = embedding_service.embed("Développeur React TypeScript interfaces web")
    frontend2 = embedding_service.embed("Frontend developer React TypeScript web")
    finance = embedding_service.embed("Comptable audit fiscalité bilan")
    sim_close = embedding_service.cosine(frontend, frontend2)
    sim_far = embedding_service.cosine(frontend, finance)
    assert sim_close > sim_far
    assert sim_close > 0.2


def test_empty_text_gives_zero_vector():
    v = embedding_service.embed("")
    assert v == [0.0] * embedding_service.dim


# ── Fabrique de données ───────────────────────────────────────────────────────

async def _make_job(db: AsyncSession, title: str, skills: list[str], description: str) -> JobOffer:
    job = JobOffer(id=uuid.uuid4(), title=title, required_skills=skills, description=description)
    db.add(job)
    await db.flush()
    return job


async def _make_analyzed_application(
    db: AsyncSession, job: JobOffer, *, name: str, skills: list[str],
    titles: list[str], years: float, raw: str = "",
) -> Application:
    user = User(
        id=uuid.uuid4(), email=f"{name.lower().replace(' ', '.')}@example.com",
        username=name.lower().replace(" ", "_"),
        hashed_password=hash_password(VALID_PASSWORD), full_name=name,
        role=UserRole.CANDIDAT, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidate = Candidate(id=uuid.uuid4(), user_id=user.id, full_name=name)
    db.add(candidate)
    await db.flush()
    application = Application(
        id=uuid.uuid4(), candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path="cv.pdf", status="PENDING",
    )
    db.add(application)
    await db.flush()
    analysis = CVAnalysis(
        application_id=application.id, candidate_id=candidate.id,
        raw_text=raw, extracted_skills=skills, extracted_job_titles=titles,
        extracted_experience_years=years, extracted_keywords=skills,
        is_parsed=True,
    )
    db.add(analysis)
    await db.flush()
    return application


async def _seed_semantic_dataset(db: AsyncSession):
    """1 offre frontend + 3 CV : frontend fort, frontend proche, comptable."""
    job = await _make_job(
        db, "Développeur Frontend React",
        ["react", "typescript", "css"],
        "Développement d'interfaces web modernes en React et TypeScript.",
    )
    app_react = await _make_analyzed_application(
        db, job, name="Sara Frontend",
        skills=["react", "typescript", "css", "html"],
        titles=["Développeur Frontend React"], years=4,
        raw="Développeur frontend spécialisé React TypeScript interfaces web.",
    )
    app_vue = await _make_analyzed_application(
        db, job, name="Karim Vuejs",
        skills=["vue", "javascript", "css"],
        titles=["Développeur Frontend"], years=3,
        raw="Développeur frontend web javascript interfaces.",
    )
    app_compta = await _make_analyzed_application(
        db, job, name="Mounir Compta",
        skills=["comptabilité", "audit", "excel"],
        titles=["Comptable senior"], years=8,
        raw="Comptable senior spécialisé audit et fiscalité, bilans annuels.",
    )
    for application in (app_react, app_vue, app_compta):
        analysis = (
            await db.execute(select(CVAnalysis).where(CVAnalysis.application_id == application.id))
        ).scalar_one()
        await semantic_service.index_cv(db, analysis)
    await semantic_service.index_job(db, job)
    await db.commit()
    return job, app_react, app_vue, app_compta


# ── Indexation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_is_upsert_not_duplicate(db: AsyncSession):
    job = await _make_job(db, "DevOps Engineer", ["docker", "kubernetes"], "Infra cloud." * 3)
    await semantic_service.index_job(db, job)
    await semantic_service.index_job(db, job)  # 2e indexation → update, pas insert
    count = (
        await db.execute(
            select(func.count(Embedding.id)).where(
                Embedding.entity_type == "job_offer", Embedding.entity_id == job.id
            )
        )
    ).scalar_one()
    assert count == 1


# ── Matching CV ↔ offre ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_match_ranks_relevant_candidate_first(db: AsyncSession):
    job, app_react, app_vue, app_compta = await _seed_semantic_dataset(db)

    result = await semantic_service.match_candidates_for_job(db, job.id, limit=10)
    assert result["job_title"] == "Développeur Frontend React"
    results = result["results"]
    assert len(results) == 3

    ids_in_order = [r["application_id"] for r in results]
    # Le frontend React doit sortir premier, le comptable dernier.
    assert ids_in_order[0] == str(app_react.id)
    assert ids_in_order[-1] == str(app_compta.id)
    # Scores décroissants et bornés 0..100.
    scores = [r["semantic_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    # Enrichissement présent.
    assert results[0]["candidate_name"] == "Sara Frontend"
    assert "react" in results[0]["skills"]
    # Le compte utilisateur accompagne chaque résultat : la fiche back-office
    # s'ouvre sur /admin/users/:id, pas sur l'identifiant candidat.
    assert results[0]["user_id"] is not None
    assert results[0]["user_id"] != results[0]["candidate_id"]


@pytest.mark.asyncio
async def test_similar_candidates_excludes_self(db: AsyncSession):
    job, app_react, app_vue, app_compta = await _seed_semantic_dataset(db)

    result = await semantic_service.similar_candidates(db, app_react.id, limit=5)
    results = result["results"]
    returned_ids = {r["application_id"] for r in results}
    assert str(app_react.id) not in returned_ids  # jamais soi-même
    assert len(results) == 2
    # Le frontend Vue est plus proche du frontend React que le comptable.
    assert results[0]["application_id"] == str(app_vue.id)


# ── API ───────────────────────────────────────────────────────────────────────

async def _make_admin_token(client: AsyncClient, db: AsyncSession) -> str:
    admin = User(
        id=uuid.uuid4(), email="admin_sem@example.com", username="admin_sem",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Admin Sem",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    )
    db.add(admin)
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_sem@example.com", "password": VALID_PASSWORD},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_semantic_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/semantic/status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_semantic_api_end_to_end(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)
    job, app_react, app_vue, app_compta = await _seed_semantic_dataset(db)

    # Status : backend hash en tests, compteurs cohérents.
    st = (await client.get("/api/v1/semantic/status", headers=_auth(token))).json()
    assert st["effective_backend"] == "hash-v1"
    assert st["indexed_jobs"] >= 1 and st["indexed_cvs"] == 3

    # Matching par offre.
    match = await client.get(
        f"/api/v1/semantic/jobs/{job.id}/match?limit=5", headers=_auth(token)
    )
    assert match.status_code == 200, match.text
    assert match.json()["results"][0]["candidate_name"] == "Sara Frontend"

    # Candidats similaires.
    similar = await client.get(
        f"/api/v1/semantic/applications/{app_react.id}/similar", headers=_auth(token)
    )
    assert similar.status_code == 200
    assert {r["application_id"] for r in similar.json()["results"]} == {
        str(app_vue.id), str(app_compta.id)
    }

    # Reindex : idempotent, retourne des compteurs.
    reindex = await client.post("/api/v1/semantic/reindex", headers=_auth(token))
    assert reindex.status_code == 200
    body = reindex.json()
    assert body["jobs_indexed"] >= 1 and body["cvs_indexed"] == 3

    # 404 propres.
    r404 = await client.get(
        f"/api/v1/semantic/jobs/{uuid.uuid4()}/match", headers=_auth(token)
    )
    assert r404.status_code == 404
    c404 = await client.get(
        f"/api/v1/semantic/applications/{uuid.uuid4()}/similar", headers=_auth(token)
    )
    assert c404.status_code == 404
