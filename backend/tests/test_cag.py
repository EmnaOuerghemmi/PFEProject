"""
Tests du moteur CAG (Cache-Augmented Generation) extractif, sans LLM (V1.7).

Backend d'embedding « hash » (déterministe, forcé dans conftest). Couvre :
  - seed + indexation (cache d'embeddings)
  - réponse extractive : renvoie l'entrée KB pertinente, avec sources + confiance
  - cache de réponses (2e appel → from_cache = True)
  - Q&A sur CV : renvoie un passage EXACT du CV (extraction, pas de génération)
  - CRUD base de connaissances + API + RBAC
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
from app.models.knowledge import KnowledgeEntry, CVChunk
from app.services.cag_service import cag_service, _split_passages
from tests.conftest import VALID_PASSWORD


@pytest.fixture(autouse=True)
def _reset_cag_caches():
    """Isole les caches mémoire du service entre les tests."""
    cag_service._invalidate_caches()
    yield
    cag_service._invalidate_caches()


# ── Découpage ─────────────────────────────────────────────────────────────────

def test_split_passages_filters_and_splits():
    text = "Court.\nJ'ai managé une équipe de 5 développeurs pendant 3 ans. " \
           "Expert en Python, Django et PostgreSQL pour des applications web."
    passages = _split_passages(text)
    assert all(len(p) >= 20 for p in passages)
    assert any("managé une équipe" in p for p in passages)


# ── Service : seed / index / ask ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_and_index_idempotent(db: AsyncSession):
    created = await cag_service.seed_default_kb(db)
    assert created > 0
    again = await cag_service.seed_default_kb(db)
    assert again == 0

    indexed = await cag_service.index_knowledge(db)
    assert indexed == created  # tout est embeddé une fois
    # Ré-indexer sans changement de backend ne réembbed rien.
    assert await cag_service.index_knowledge(db) == 0
    await db.commit()

    total = (await db.execute(select(func.count(KnowledgeEntry.id)))).scalar_one()
    assert total == created


@pytest.mark.asyncio
async def test_ask_returns_grounded_answer_with_sources(db: AsyncSession):
    await cag_service.seed_default_kb(db)
    await cag_service.index_knowledge(db)
    await db.commit()

    res = await cag_service.ask(db, "Comment puis-je postuler à une offre ?")
    assert res["confidence"] > 0
    assert res["sources"], "des sources doivent être renvoyées"
    # La réponse est EXTRAITE d'une entrée existante (zéro hallucination).
    contents = {
        e.content for e in (await db.execute(select(KnowledgeEntry))).scalars().all()
    }
    assert res["answer"] in contents
    # La meilleure source concerne bien la candidature.
    assert res["sources"][0]["category"] in {"CANDIDATURE", "PROCESS"}


@pytest.mark.asyncio
async def test_answer_cache_hit(db: AsyncSession):
    await cag_service.seed_default_kb(db)
    await cag_service.index_knowledge(db)
    await db.commit()

    q = "Comment se déroule un entretien ?"
    first = await cag_service.ask(db, q)
    assert first["from_cache"] is False
    second = await cag_service.ask(db, q)
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]


# ── Service : Q&A sur CV ──────────────────────────────────────────────────────

async def _make_analyzed_application(db: AsyncSession, raw_text: str) -> Application:
    user = User(
        id=uuid.uuid4(), email=f"cand_{uuid.uuid4().hex[:6]}@ex.com",
        username=uuid.uuid4().hex[:8], hashed_password=hash_password(VALID_PASSWORD),
        full_name="Candidat CV", role=UserRole.CANDIDAT, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()
    candidate = Candidate(id=uuid.uuid4(), user_id=user.id, full_name="Candidat CV")
    job = JobOffer(id=uuid.uuid4(), title="Backend Developer", description="x")
    db.add_all([candidate, job])
    await db.flush()
    application = Application(
        id=uuid.uuid4(), candidate_id=candidate.id, job_offer_id=job.id,
        cv_file_path="cv.pdf", status="PENDING",
    )
    db.add(application)
    await db.flush()
    db.add(CVAnalysis(
        application_id=application.id, candidate_id=candidate.id, raw_text=raw_text,
        extracted_skills=[], extracted_job_titles=[], extracted_keywords=[], is_parsed=True,
    ))
    await db.flush()
    return application


@pytest.mark.asyncio
async def test_ask_cv_extracts_exact_passage(db: AsyncSession):
    raw = (
        "Ingénieur logiciel diplômé de l'ENSI. "
        "J'ai managé une équipe de cinq développeurs pendant trois ans. "
        "Compétences : Python, Django, Kubernetes et AWS. "
        "Passionné de course à pied et de photographie."
    )
    app = await _make_analyzed_application(db, raw)
    await db.commit()

    res = await cag_service.ask_cv(db, app.id, "Ce candidat a-t-il managé une équipe ?")
    assert res["confidence"] > 0
    # La réponse est un passage EXACT du CV.
    assert res["answer"] in raw
    assert "équipe" in res["answer"].lower()
    assert res["candidate_name"] == "Candidat CV"

    # Les chunks sont mis en cache (calculés une seule fois).
    n_chunks = (await db.execute(
        select(func.count(CVChunk.id)).where(CVChunk.application_id == app.id)
    )).scalar_one()
    assert n_chunks > 0
    # 2e question → réutilise les chunks cachés (pas de recomptage).
    await cag_service.ask_cv(db, app.id, "Quelles technologies maîtrise-t-il ?")
    n_chunks_2 = (await db.execute(
        select(func.count(CVChunk.id)).where(CVChunk.application_id == app.id)
    )).scalar_one()
    assert n_chunks_2 == n_chunks


# ── API + RBAC ────────────────────────────────────────────────────────────────

async def _make_admin_token(client: AsyncClient, db: AsyncSession) -> str:
    admin = User(
        id=uuid.uuid4(), email="admin_cag@example.com", username="admin_cag",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Admin CAG",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    )
    db.add(admin)
    await db.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin_cag@example.com", "password": VALID_PASSWORD},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_cag_ask_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/cag/ask", json={"question": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cag_api_flow(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)

    # Seed via l'API + statut (idempotent → 200).
    seed = await client.post("/api/v1/cag/seed", headers=_auth(token))
    assert seed.status_code == 200
    st = (await client.get("/api/v1/cag/status", headers=_auth(token))).json()
    assert st["knowledge_entries"] > 0
    assert "extractif" in st["mode"]

    # Ask.
    ask = await client.post("/api/v1/cag/ask", json={"question": "Comment postuler ?"},
                            headers=_auth(token))
    assert ask.status_code == 200
    body = ask.json()
    assert body["answer"] and body["sources"]

    # Ajout d'une entrée avec un terme DISTINCTIF ('télétravail' n'apparaît dans
    # aucune autre entrée) → recherche déterministe même en backend hash lexical.
    add = await client.post(
        "/api/v1/cag/knowledge",
        json={"title": "Politique de télétravail",
              "content": "Le télétravail est autorisé deux jours par semaine après validation du manager.",
              "category": "POLITIQUE"},
        headers=_auth(token),
    )
    assert add.status_code == 201
    entry_id = add.json()["id"]

    ask2 = await client.post("/api/v1/cag/ask",
                             json={"question": "télétravail par semaine autorisé"}, headers=_auth(token))
    body2 = ask2.json()
    # Le terme unique impose l'entrée en tête : réponse extraite = son contenu.
    assert "télétravail" in body2["answer"].lower()
    assert body2["sources"][0]["title"] == "Politique de télétravail"

    dele = await client.delete(f"/api/v1/cag/knowledge/{entry_id}", headers=_auth(token))
    assert dele.status_code == 204


@pytest.mark.asyncio
async def test_cag_cv_ask_404_and_409(client: AsyncClient, db: AsyncSession):
    token = await _make_admin_token(client, db)

    # 404 : candidature inexistante.
    r404 = await client.post(f"/api/v1/cag/cv/{uuid.uuid4()}/ask",
                             json={"question": "x?"}, headers=_auth(token))
    assert r404.status_code == 404

    # 409 : candidature sans CV analysé.
    user = User(id=uuid.uuid4(), email="c409@ex.com", username="c409",
                hashed_password=hash_password(VALID_PASSWORD), full_name="C",
                role=UserRole.CANDIDAT, is_active=True, is_verified=True)
    db.add(user); await db.flush()
    cand = Candidate(id=uuid.uuid4(), user_id=user.id, full_name="C")
    job = JobOffer(id=uuid.uuid4(), title="T", description="x")
    db.add_all([cand, job]); await db.flush()
    app = Application(id=uuid.uuid4(), candidate_id=cand.id, job_offer_id=job.id,
                      cv_file_path="cv.pdf", status="PENDING")
    db.add(app); await db.commit()

    r409 = await client.post(f"/api/v1/cag/cv/{app.id}/ask",
                             json={"question": "x?"}, headers=_auth(token))
    assert r409.status_code == 409
