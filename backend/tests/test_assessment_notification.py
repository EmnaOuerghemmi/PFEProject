"""
Lot 2 — statut « en test » et alerte de fin au RH.

Le point qui justifie tout ce lot : **une session de test se ferme par quatre
chemins différents**, et c'est le dernier qui compte le plus.

1. Le candidat clique « terminer ».
2. Il répond à la dernière question.
3. Son temps s'écoule pendant qu'il compose.
4. Il ferme son navigateur, et le balayage referme la session deux minutes plus
   tard.

C'est le quatrième cas dont le RH doit être averti : sans alerte, un candidat
qui disparaît en cours de route ne se signale à personne. Ces tests vérifient
que les quatre chemins produisent le même résultat — et une seule alerte.
"""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.application_status import ApplicationStatus
from app.models.assessment import QuestionStatus, SessionStatus, TestSession
from app.models.notification import Notification
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.user import User, UserRole
from app.services.assessment_service import (
    assessment_service as svc, send_due_test_notifications, sweep_expired_sessions,
)
from app.utils.helpers import utcnow

from tests.conftest import VALID_PASSWORD


async def _contexte(db: AsyncSession, n=3) -> tuple[TestSession, Application, User]:
    job = JobOffer(title="Développeur Full Stack", description="Poste de test.",
                   required_skills=["Angular"], is_active=True, status="PUBLISHED")
    db.add(job)
    await db.flush()

    questions = []
    for i in range(n):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question numéro {i} sur le poste ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
        })
        q.status = QuestionStatus.ACTIVE
        questions.append(q)

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
                       status=ApplicationStatus.TEST_SENT.value)
    db.add(app_)

    rh_suffixe = uuid.uuid4().hex[:6]
    rh = User(id=uuid.uuid4(), email=f"rh_{rh_suffixe}@example.com",
              username=f"rh_{rh_suffixe}", hashed_password=hash_password(VALID_PASSWORD),
              full_name="RH Référent", role=UserRole.ADMIN,
              is_active=True, is_verified=True)
    db.add(rh)
    await db.flush()

    session = await svc.create_session(db, app_.id, [q.id for q in questions])
    session.sent_by = rh.id
    await db.commit()
    await db.refresh(session)
    await db.refresh(app_)
    return session, app_, rh


def _capturer_courriels(monkeypatch) -> list[dict]:
    """Les envois sont interceptés : aucun SMTP dans la suite de tests."""
    envois: list[dict] = []
    import app.services.email_service as email_service

    async def _faux(**kw):
        envois.append(kw)
        return True

    monkeypatch.setattr(email_service, "send_technical_test_completed", _faux)
    return envois


# ── Le statut suit le test ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ouvrir_le_lien_bascule_la_candidature_en_test(db: AsyncSession):
    session, app_, _ = await _contexte(db)
    assert app_.status == ApplicationStatus.TEST_SENT.value

    await svc.open_session(db, session.token)
    await db.commit()
    await db.refresh(app_)
    assert app_.status == ApplicationStatus.EN_TEST.value


@pytest.mark.asyncio
async def test_la_correction_bascule_la_candidature_en_test_passe(db: AsyncSession):
    session, app_, _ = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()
    await db.refresh(app_)
    assert app_.status == ApplicationStatus.TEST_DONE.value


@pytest.mark.asyncio
async def test_le_report_ne_fait_jamais_reculer_une_candidature(db: AsyncSession):
    """
    Un RH peut avoir avancé la candidature pendant que le test traînait. La
    session ne doit pas la ramener en arrière : le report est opportuniste, et
    c'est la session qui reste la source faisant foi sur le test.
    """
    session, app_, _ = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await db.commit()

    app_.status = ApplicationStatus.INTERVIEW_SCHEDULED.value
    await db.commit()

    await svc.score_session(db, session)
    await db.commit()
    await db.refresh(app_)
    assert app_.status == ApplicationStatus.INTERVIEW_SCHEDULED.value


# ── L'alerte, par les quatre chemins ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_candidat_qui_termine_declenche_lalerte(db: AsyncSession, monkeypatch):
    envois = _capturer_courriels(monkeypatch)
    session, _, rh = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()

    assert await send_due_test_notifications(db) == 1
    assert len(envois) >= 1
    assert any(e["to_email"] == rh.email for e in envois), \
        "le RH qui a envoyé le test doit être prévenu"


@pytest.mark.asyncio
async def test_le_candidat_qui_ferme_son_navigateur_declenche_lalerte(
    db: AsyncSession, monkeypatch
):
    """
    LE cas qui justifie le mécanisme. Personne ne clique « terminer », aucune
    requête n'arrive : seul le balayage referme la session, et sans alerte le
    RH n'apprendrait jamais que ce candidat a composé.
    """
    envois = _capturer_courriels(monkeypatch)
    session, app_, rh = await _contexte(db)
    session = await svc.open_session(db, session.token)
    # Le temps s'écoule pendant que le navigateur est fermé.
    session.started_at = utcnow() - timedelta(minutes=session.duration_minutes + 5)
    await db.commit()

    assert await sweep_expired_sessions(db) == 1
    assert await send_due_test_notifications(db) == 1

    await db.refresh(session)
    await db.refresh(app_)
    assert session.status == SessionStatus.EXPIRE
    assert app_.status == ApplicationStatus.TEST_DONE.value
    assert any(e["to_email"] == rh.email for e in envois)
    assert envois[0]["outcome"] == "EXPIRE"


@pytest.mark.asyncio
async def test_un_lien_jamais_ouvert_ne_declenche_pas_dalerte(
    db: AsyncSession, monkeypatch
):
    """
    Rien n'a été rendu : il n'y a rien à annoncer. Prévenir ici noierait les
    vraies alertes sous des non-événements.
    """
    envois = _capturer_courriels(monkeypatch)
    session, _, _ = await _contexte(db)
    session.link_expires_at = utcnow() - timedelta(hours=1)
    await db.commit()

    await sweep_expired_sessions(db)
    await db.refresh(session)
    assert session.status == SessionStatus.ABANDONNE
    assert session.submitted_at is None

    assert await send_due_test_notifications(db) == 0
    assert envois == []


# ── Idempotence ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deux_passages_du_balayage_nenvoient_quune_fois(
    db: AsyncSession, monkeypatch
):
    """La boucle repasse toutes les deux minutes : sans garde, elle spammerait."""
    envois = _capturer_courriels(monkeypatch)
    session, _, _ = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()

    assert await send_due_test_notifications(db) == 1
    premier = len(envois)
    assert await send_due_test_notifications(db) == 0
    assert len(envois) == premier


@pytest.mark.asyncio
async def test_la_marque_est_posee_avant_lenvoi(db: AsyncSession, monkeypatch):
    """
    Si le serveur de messagerie tombe, on perd une alerte — pas la boucle. Sans
    cette précaution, le balayage réessaierait toutes les deux minutes pour
    toujours.
    """
    import app.services.email_service as email_service

    async def _echoue(**_kw):
        raise RuntimeError("SMTP indisponible")

    monkeypatch.setattr(email_service, "send_technical_test_completed", _echoue)

    session, _, _ = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()

    await send_due_test_notifications(db)
    await db.refresh(session)
    assert session.notified_at is not None, "la marque doit survivre à l'échec d'envoi"
    assert await send_due_test_notifications(db) == 0


# ── Destinataires ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_rh_qui_a_envoye_recoit_une_notification_en_application(
    db: AsyncSession, monkeypatch
):
    _capturer_courriels(monkeypatch)
    session, _, rh = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()
    await send_due_test_notifications(db)

    notifs = (await db.execute(
        select(Notification).where(
            Notification.recipient_id == rh.id,
            Notification.type == "TEST_COMPLETED",
        )
    )).scalars().all()
    assert len(notifs) == 1
    assert "Candidat Test" in notifs[0].message


@pytest.mark.asyncio
async def test_sans_expediteur_connu_les_administrateurs_sont_prevenus(
    db: AsyncSession, monkeypatch
):
    """Un test envoyé avant ce lot n'a pas d'expéditeur : personne ne doit être oublié."""
    envois = _capturer_courriels(monkeypatch)
    session, _, _ = await _contexte(db)
    session.sent_by = None
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()

    assert await send_due_test_notifications(db) == 1
    assert envois, "les administrateurs doivent recevoir l'alerte"


@pytest.mark.asyncio
async def test_lalerte_porte_la_note_et_le_lien_du_backoffice(
    db: AsyncSession, monkeypatch
):
    envois = _capturer_courriels(monkeypatch)
    session, app_, _ = await _contexte(db)
    session = await svc.open_session(db, session.token)
    await svc.score_session(db, session)
    await db.commit()
    await send_due_test_notifications(db)

    courriel = envois[0]
    assert courriel["candidate_name"] == "Candidat Test"
    assert courriel["score"] is not None
    assert courriel["question_count"] == 3
    assert str(courriel["application_id"]) == str(app_.id)
