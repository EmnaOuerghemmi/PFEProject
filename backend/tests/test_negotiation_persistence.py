"""
Tests de la persistance des négociations (feature « négociation en base »).

Couvre :
  - le repository (create / add_round / finalize / get_latest / list / stats)
  - la cascade ORM Negotiation -> NegotiationRound
  - la sérialisation to_summary
  - l'intégration bout-en-bout via POST /negotiations/initiate + GET /history

Même setup sqlite + ASGITransport que les autres tests.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.negotiation import Negotiation, NegotiationRound
from app.services.negotiation_repository import negotiation_repository


# ── Repository / modèle ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_negotiation_persists_row(db: AsyncSession):
    neg = await negotiation_repository.create(
        db,
        job_id="job-1",
        candidate_id="cand-1",
        initial_offer=2000.0,
        predicted_salary=2500.0,
        confidence=0.8,
    )
    assert neg.id is not None
    assert neg.status == "ONGOING"
    assert neg.rounds_count == 0

    fetched = (
        await db.execute(select(Negotiation).where(Negotiation.job_id == "job-1"))
    ).scalar_one()
    assert fetched.initial_offer == 2000.0
    assert fetched.predicted_salary == 2500.0


@pytest.mark.asyncio
async def test_add_round_increments_counter(db: AsyncSession):
    neg = await negotiation_repository.create(
        db, job_id="job-2", candidate_id="cand-2", initial_offer=1800.0
    )
    await negotiation_repository.add_round(
        db, neg, actor="employer", amount=1800.0, decision="pending", reason="offre initiale"
    )
    await negotiation_repository.add_round(
        db, neg, actor="candidate", amount=2200.0, decision="counter_offer", reason="contre-offre"
    )
    assert neg.rounds_count == 2

    rounds = await negotiation_repository.list_rounds(db, neg.id)
    assert [r.round_number for r in rounds] == [1, 2]
    assert rounds[0].actor == "employer"
    assert rounds[1].actor == "candidate"
    assert rounds[1].amount == 2200.0


@pytest.mark.asyncio
async def test_finalize_sets_outcome(db: AsyncSession):
    neg = await negotiation_repository.create(
        db, job_id="job-3", candidate_id="cand-3", initial_offer=2000.0
    )
    await negotiation_repository.finalize(
        db, neg, status="ACCEPTED", final_salary=2400.0, reason="Accord trouvé"
    )
    assert neg.status == "ACCEPTED"
    assert neg.final_salary == 2400.0
    assert neg.reason == "Accord trouvé"


@pytest.mark.asyncio
async def test_cascade_delete_removes_rounds(db: AsyncSession):
    neg = await negotiation_repository.create(
        db, job_id="job-4", candidate_id="cand-4", initial_offer=1500.0
    )
    await negotiation_repository.add_round(db, neg, actor="employer", amount=1500.0)
    neg_id = neg.id

    await db.delete(neg)
    await db.flush()

    remaining = (
        await db.execute(
            select(NegotiationRound).where(NegotiationRound.negotiation_id == neg_id)
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_get_latest_by_job(db: AsyncSession):
    await negotiation_repository.create(
        db, job_id="job-5", candidate_id="cand-5", initial_offer=1000.0
    )
    latest = await negotiation_repository.get_latest_by_job(db, "job-5")
    assert latest is not None
    assert latest.job_id == "job-5"

    assert await negotiation_repository.get_latest_by_job(db, "does-not-exist") is None


@pytest.mark.asyncio
async def test_list_and_stats(db: AsyncSession):
    a = await negotiation_repository.create(db, job_id="j-a", candidate_id="c", initial_offer=1000.0)
    await negotiation_repository.finalize(db, a, status="ACCEPTED", final_salary=1100.0)
    b = await negotiation_repository.create(db, job_id="j-b", candidate_id="c", initial_offer=2000.0)
    await negotiation_repository.finalize(db, b, status="REJECTED", final_salary=2000.0)

    all_items = await negotiation_repository.list(db)
    assert len(all_items) == 2

    accepted = await negotiation_repository.list(db, status="ACCEPTED")
    assert len(accepted) == 1
    assert accepted[0].status == "ACCEPTED"

    stats = await negotiation_repository.stats(db)
    assert stats["total"] == 2
    assert stats["accepted"] == 1
    assert stats["rejected"] == 1


@pytest.mark.asyncio
async def test_to_summary_shape(db: AsyncSession):
    neg = await negotiation_repository.create(
        db, job_id="job-6", candidate_id="cand-6", initial_offer=2000.0,
        predicted_salary=2500.0, confidence=0.7,
    )
    await negotiation_repository.add_round(
        db, neg, actor="candidate", amount=2300.0, decision="counter_offer", reason="r1"
    )
    rounds = await negotiation_repository.list_rounds(db, neg.id)
    summary = negotiation_repository.to_summary(neg, rounds)

    assert summary["job_id"] == "job-6"
    assert summary["predicted_salary"] == 2500.0
    assert summary["rounds_count"] == 1
    assert len(summary["rounds"]) == 1
    assert summary["rounds"][0]["actor"] == "candidate"
    assert summary["rounds"][0]["amount"] == 2300.0


# ── Intégration API ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/negotiations/history/whatever")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_initiate_persists_and_history_returns_it(client: AsyncClient, db: AsyncSession):
    # Un compte RH : la négociation salariale lui est réservée (rbac_policy.csv).
    from tests.test_interview_second_round import _rh
    headers = await _rh(client, db)

    # Offre généreuse -> décision ACCEPT immédiate (chemin rapide, sans sleeps).
    payload = {
        "candidate_id": "cand-int-1",
        "employer_offer": 6000,
        "job_data": {
            "job_id": "job-int-1",
            "title": "Senior Data Scientist",
            "description": "Poste data science",
            "python": 1,
            "aws": 1,
        },
    }
    resp = await client.post("/api/v1/negotiations/initiate", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text

    # La négociation doit être persistée et récupérable via /history.
    hist = await client.get("/api/v1/negotiations/history/job-int-1", headers=headers)
    assert hist.status_code == 200, hist.text
    data = hist.json()
    assert data["job_id"] == "job-int-1"
    assert data["candidate_id"] == "cand-int-1"
    assert data["status"] in {"ACCEPTED", "REJECTED", "COMPROMIS", "ONGOING"}
    assert data["initial_offer"] == 6000
    # Au moins le round de l'offre initiale employeur est enregistré.
    assert data["rounds_count"] >= 1
    assert any(r["actor"] == "employer" for r in data["rounds"])
