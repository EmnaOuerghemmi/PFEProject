"""
Lot 1 — l'état du test dans le classement des candidats.

Ce que ces tests protègent :

1. **L'éligibilité est décidée par le serveur.** Le seuil de score ne descend
   pas jusqu'au navigateur. Un chiffre métier dupliqué côté client finit
   toujours par diverger de celui du serveur — les seuils 85 et 30, codés en
   dur dans le gabarit, en sont déjà la démonstration.
2. **Un candidat sous le seuil n'est jamais bloqué pour l'entretien.** Il ne
   peut pas passer de test ; lui opposer l'absence de test le condamnerait.
3. **Une requête, pas une par candidat.** Le classement peut compter des
   dizaines de lignes.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.application_status import ApplicationStatus
from app.models.assessment import QuestionStatus, SessionStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.assessment_service import assessment_service as svc

from tests.conftest import VALID_PASSWORD


async def _offre(db: AsyncSession) -> JobOffer:
    job = JobOffer(
        title="Développeur Full Stack", description="Poste de test.",
        required_skills=["Angular", "Java"], required_experience_years=2,
        is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def _candidat_note(db: AsyncSession, job: JobOffer, score: float) -> Application:
    """Une candidature avec un score de CV — c'est lui qui décide de l'éligibilité."""
    suffixe = uuid.uuid4().hex[:8]
    user = User(email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD),
                full_name="Candidat Test", is_active=True, is_verified=True)
    db.add(user)
    await db.flush()
    candidat = Candidate(user_id=user.id, full_name="Candidat Test")
    db.add(candidat)
    await db.flush()
    app_ = Application(candidate_id=candidat.id, job_offer_id=job.id,
                       cv_file_path="/tmp/cv.pdf",
                       status=ApplicationStatus.REVIEWED.value)
    db.add(app_)
    await db.flush()
    db.add(CandidateScore(
        application_id=app_.id, job_offer_id=job.id, candidate_id=candidat.id,
        total_score=score, skills_score=score, experience_score=score,
        education_score=score,
    ))
    await db.commit()
    await db.refresh(app_)
    return app_


async def _session_de_test(db: AsyncSession, job: JobOffer, app_: Application,
                           statut: SessionStatus, note: float | None = None):
    questions = []
    for i in range(3):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question numéro {i} sur le poste ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
        })
        q.status = QuestionStatus.ACTIVE
        questions.append(q)
    await db.commit()
    session = await svc.create_session(db, app_.id, [q.id for q in questions])
    session.status = statut
    session.score = note
    await db.commit()
    await db.refresh(session)
    return session


async def _rh(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
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


async def _classement(client: AsyncClient, db: AsyncSession, job: JobOffer) -> list[dict]:
    resp = await client.get(f"/api/v1/recruitment/jobs/{job.id}/ranking",
                            headers=await _rh(client, db))
    assert resp.status_code == 200, resp.text
    return resp.json()["ranking"]


# ── Éligibilité ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_seuil_decide_qui_peut_recevoir_un_test(
    client: AsyncClient, db: AsyncSession
):
    """La vérification du lot : deux candidats, un seul éligible."""
    job = await _offre(db)
    seuil = settings.TEST_ELIGIBILITY_MIN_SCORE
    au_dessus = await _candidat_note(db, job, seuil + 12)
    en_dessous = await _candidat_note(db, job, seuil - 9)

    par_app = {l["application_id"]: l for l in await _classement(client, db, job)}

    assert par_app[str(au_dessus.id)]["can_send_test"] is True
    assert par_app[str(en_dessous.id)]["can_send_test"] is False


@pytest.mark.asyncio
async def test_le_seuil_lui_meme_ne_sort_jamais_de_lapi(
    client: AsyncClient, db: AsyncSession
):
    """
    Le navigateur reçoit une décision, pas la règle qui l'a produite. Sinon le
    seuil vit en deux endroits — et diverge.
    """
    job = await _offre(db)
    await _candidat_note(db, job, 70)
    ligne = (await _classement(client, db, job))[0]
    assert "can_send_test" in ligne
    assert not any("seuil" in c or "threshold" in c.lower() for c in ligne)


@pytest.mark.asyncio
async def test_un_test_deja_ouvert_interdit_den_envoyer_un_second(
    client: AsyncClient, db: AsyncSession
):
    """Le service n'autorise qu'une session active : le bouton doit le refléter."""
    job = await _offre(db)
    app_ = await _candidat_note(db, job, 80)
    await _session_de_test(db, job, app_, SessionStatus.EN_COURS)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_send_test"] is False
    assert ligne["test_status"] == "EN_COURS"


@pytest.mark.asyncio
async def test_un_test_termine_rouvre_la_possibilite_den_envoyer_un_autre(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_ = await _candidat_note(db, job, 80)
    await _session_de_test(db, job, app_, SessionStatus.TERMINE, note=64.0)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_send_test"] is True
    assert ligne["test_status"] == "TERMINE"
    assert ligne["test_score"] == 64.0


# ── Entretien ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lentretien_attend_le_test_dun_candidat_eligible(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_ = await _candidat_note(db, job, 80)
    await _session_de_test(db, job, app_, SessionStatus.ENVOYE)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_schedule_interview"] is False


@pytest.mark.asyncio
async def test_un_candidat_sous_le_seuil_nest_jamais_bloque(
    client: AsyncClient, db: AsyncSession
):
    """
    Le cas qui coûte le plus cher si on l'oublie : sous le seuil, aucun test
    n'est possible. Exiger un test pour l'entretien condamnerait ces candidats
    à ne jamais être reçus — alors que rencontrer quelqu'un reste une décision
    humaine.
    """
    job = await _offre(db)
    await _candidat_note(db, job, settings.TEST_ELIGIBILITY_MIN_SCORE - 20)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_send_test"] is False
    assert ligne["can_schedule_interview"] is True


@pytest.mark.asyncio
async def test_un_test_rate_nempeche_pas_lentretien(
    client: AsyncClient, db: AsyncSession
):
    """Le test informe la décision, il ne la prend pas."""
    job = await _offre(db)
    app_ = await _candidat_note(db, job, 80)
    await _session_de_test(db, job, app_, SessionStatus.TERMINE, note=15.0)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_schedule_interview"] is True


@pytest.mark.asyncio
async def test_un_test_expire_ne_bloque_pas_indefiniment(
    client: AsyncClient, db: AsyncSession
):
    """Sinon un candidat qui abandonne son test reste coincé pour toujours."""
    job = await _offre(db)
    app_ = await _candidat_note(db, job, 80)
    await _session_de_test(db, job, app_, SessionStatus.EXPIRE, note=30.0)

    ligne = (await _classement(client, db, job))[0]
    assert ligne["can_schedule_interview"] is True


@pytest.mark.asyncio
async def test_sans_test_envoye_le_classement_ne_dit_rien(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    await _candidat_note(db, job, 80)
    ligne = (await _classement(client, db, job))[0]
    assert ligne["test_status"] is None
    assert ligne["test_score"] is None


# ── Coût ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_classement_ne_fait_pas_une_requete_par_candidat(
    client: AsyncClient, db: AsyncSession
):
    """
    Un classement d'offre peut compter des dizaines de lignes. L'enrichissement
    se fait par requêtes groupées ; ce test échoue si quelqu'un repasse à une
    boucle.
    """
    job = await _offre(db)
    for note in (55, 60, 65, 70, 75, 80):
        await _candidat_note(db, job, note)

    compteur = {"n": 0}
    from sqlalchemy import event
    from app.db.session import engine

    def _compter(*_args, **_kwargs):
        compteur["n"] += 1

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _compter)
    try:
        lignes = await _classement(client, db, job)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter)

    assert len(lignes) == 6
    # Large, volontairement : ce test surveille un ORDRE DE GRANDEUR, pas un
    # nombre exact que le moindre ajout ferait échouer à tort. Une boucle par
    # candidat en produirait plusieurs dizaines de plus.
    assert compteur["n"] < 30, f"{compteur['n']} requêtes pour 6 candidats"


# ── Test envoyé automatiquement à la confirmation d'un entretien ──────────────
#
# Le candidat qui confirme un créneau reçoit le test AVANT l'entretien, sans
# geste du RH. Les trois gardes ci-dessous sont ce qui empêche cet automatisme
# de devenir nuisible : il ne recouvre jamais un test existant, ne contourne
# pas le seuil d'éligibilité, et ne s'invente pas de questions.

async def _vivier_actif(db: AsyncSession, job: JobOffer, n: int = 3) -> None:
    for i in range(n):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question automatique numéro {i} ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
        })
        q.status = QuestionStatus.ACTIVE
    await db.commit()


@pytest.mark.asyncio
async def test_le_test_part_tout_seul_quand_le_candidat_est_eligible(db: AsyncSession):
    """La vérification du lot : score au-dessus du seuil + vivier ⇒ session ouverte."""
    job = await _offre(db)
    await _vivier_actif(db, job)
    app_ = await _candidat_note(db, job, settings.TEST_ELIGIBILITY_MIN_SCORE + 20)

    session = await svc.auto_send_test_for_confirmed_interview(db, app_.id)
    await db.commit()

    assert session is not None
    assert session.status == SessionStatus.ENVOYE
    assert session.question_count == 3

    await db.refresh(app_)
    assert app_.status == ApplicationStatus.TEST_SENT.value


@pytest.mark.asyncio
async def test_aucun_test_automatique_sous_le_seuil(db: AsyncSession):
    """
    Le seuil d'éligibilité vaut aussi pour l'envoi automatique : le passer par
    la porte de l'entretien reviendrait à ne plus avoir de seuil du tout.
    """
    job = await _offre(db)
    await _vivier_actif(db, job)
    app_ = await _candidat_note(db, job, settings.TEST_ELIGIBILITY_MIN_SCORE - 10)

    assert await svc.auto_send_test_for_confirmed_interview(db, app_.id) is None


@pytest.mark.asyncio
async def test_un_test_deja_passe_nest_jamais_recouvert(db: AsyncSession):
    """
    Le RH a pu envoyer le test lui-même avant de proposer l'entretien — et la
    session terminée porte la note du candidat. La recréer l'effacerait.
    """
    job = await _offre(db)
    app_ = await _candidat_note(db, job, settings.TEST_ELIGIBILITY_MIN_SCORE + 20)
    deja = await _session_de_test(db, job, app_, SessionStatus.TERMINE, note=72.0)

    assert await svc.auto_send_test_for_confirmed_interview(db, app_.id) is None

    from sqlalchemy import select
    from app.models.assessment import TestSession
    sessions = (await db.execute(
        select(TestSession).where(TestSession.application_id == app_.id)
    )).scalars().all()
    assert [s.id for s in sessions] == [deja.id]
    assert sessions[0].score == 72.0


@pytest.mark.asyncio
async def test_sans_vivier_lentretien_reste_possible(db: AsyncSession):
    """
    Une offre sans questions n'a pas de test à envoyer. L'entretien, lui, est
    déjà confirmé : l'absence de vivier ne doit rien casser, juste ne rien
    faire.
    """
    job = await _offre(db)
    app_ = await _candidat_note(db, job, settings.TEST_ELIGIBILITY_MIN_SCORE + 20)

    assert await svc.auto_send_test_for_confirmed_interview(db, app_.id) is None
