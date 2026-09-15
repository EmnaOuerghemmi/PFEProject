"""
La fiche d'un utilisateur, vue par l'administration.

Deux exigences, et la première prime sur tout le reste :

1. **Aucun secret d'authentification ne sort d'ici.** Mot de passe haché,
   secret TOTP, codes de secours, jetons : ce sont des moyens d'usurper un
   compte, pas des informations de profil. Une fiche qui les laisse filtrer
   transforme une consultation en prise de contrôle.
2. **La fiche s'adapte à la personne.** Un candidat amène son dossier et ses
   candidatures ; un RH s'arrête à son compte. Rendre des sections vides pour
   un compte interne laisserait croire à une donnée manquante.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.application_status import ApplicationStatus
from app.models.assessment import QuestionStatus, SessionStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole
from app.services.assessment_service import assessment_service as svc

from tests.conftest import VALID_PASSWORD

PROFIL = "/api/v1/users/{}/profile"


async def _offre(db: AsyncSession, titre="Développeur Laravel") -> JobOffer:
    job = JobOffer(title=titre, description="Poste de test.",
                   required_skills=["Laravel", "PHP"], required_experience_years=2,
                   is_active=True, status="PUBLISHED")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def _compte(db: AsyncSession, role=UserRole.CANDIDAT, *,
                  avec_secrets=False) -> User:
    """
    Un compte de connexion normal, PAR DÉFAUT sans 2FA.

    `avec_secrets=True` n'est à passer que pour le SUJET d'une fiche — celui
    dont on vérifie que les secrets ne fuitent pas. L'activer par défaut
    casserait la connexion de tout autre compte créé pour le test : un compte
    2FA exige un code TOTP, que ces connexions de complaisance ne fournissent
    jamais, et l'authentification échouerait par 428 avant même d'atteindre ce
    que le test veut vérifier.
    """
    suffixe = uuid.uuid4().hex[:8]
    user = User(email=f"u_{suffixe}@example.com", username=f"u_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD),
                full_name="Personne Test", role=role,
                is_active=True, is_verified=True,
                totp_secret="SECRETTOTPAAAAAA" if avec_secrets else None,
                totp_enabled=avec_secrets,
                refresh_token=("jeton-de-rafraichissement-secret"
                              if avec_secrets else None))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _candidat_complet(db: AsyncSession, job: JobOffer) -> User:
    user = await _compte(db, avec_secrets=True)
    candidat = Candidate(user_id=user.id, full_name="Personne Test",
                         phone="+216 20 000 000", cv_filename="cv_emna.pdf",
                         cv_path="/var/data/cv/profil/secret_reference.pdf")
    db.add(candidat)
    await db.flush()

    app_ = Application(candidate_id=candidat.id, job_offer_id=job.id,
                       cv_file_path="/var/data/cv/secret_chemin.pdf",
                       status=ApplicationStatus.TEST_DONE.value,
                       expected_salary=2100)
    db.add(app_)
    await db.flush()
    db.add(CandidateScore(
        application_id=app_.id, job_offer_id=job.id, candidate_id=candidat.id,
        total_score=68.0, skills_score=70.0, experience_score=66.0,
        education_score=100.0, composite_score=71.5, composite_completeness=2,
        interview_score=None,
    ))

    questions = []
    for i in range(3):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question numéro {i} sur le poste ?",
            "options": ["A", "B"], "correct_answer": ["A"],
        })
        q.status = QuestionStatus.ACTIVE
        questions.append(q)
    await db.commit()

    session = await svc.create_session(db, app_.id, [q.id for q in questions])
    session.status = SessionStatus.TERMINE
    session.score = 66.7
    session.correct_count = 2
    await db.commit()
    await db.refresh(user)
    return user


async def _entete_admin(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    suffixe = uuid.uuid4().hex[:6]
    email = f"admin_{suffixe}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, username=f"admin_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="Admin",
                role=UserRole.ADMIN, is_active=True, is_verified=True))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Ce qui ne doit jamais sortir ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aucun_secret_dauthentification_ne_sort(
    client: AsyncClient, db: AsyncSession
):
    """
    Le test qui prime sur tous les autres. Ces valeurs permettent d'usurper un
    compte : les laisser filtrer ferait d'une consultation de fiche une prise
    de contrôle.
    """
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    brut = (await client.get(PROFIL.format(user.id),
                             headers=await _entete_admin(client, db))).text

    assert "hashed_password" not in brut
    assert "SECRETTOTPAAAAAA" not in brut
    assert "totp_secret" not in brut
    assert "jeton-de-rafraichissement-secret" not in brut
    assert "refresh_token" not in brut


@pytest.mark.asyncio
async def test_le_chemin_du_cv_sur_disque_ne_sort_pas(
    client: AsyncClient, db: AsyncSession
):
    """
    Le CHEMIN de la copie liée à une candidature (`Application.cv_file_path`)
    ne sort jamais — lui n'a aucun usage côté écran. Celui du CV de référence
    (`Candidate.cv_path`), en revanche, sert désormais à construire le lien
    d'aperçu : c'est la même exposition, déjà acceptée, que `cv_file_path` sur
    chaque candidature.
    """
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()

    assert "secret_chemin.pdf" not in str(corps)         # copie de candidature
    assert corps["candidate"]["cv_path"] == "/var/data/cv/profil/secret_reference.pdf"
    assert corps["candidate"]["cv_filename"] == "cv_emna.pdf"


@pytest.mark.asyncio
async def test_le_chemin_du_cv_de_reference_reste_reserve_au_rh(
    client: AsyncClient, db: AsyncSession
):
    """
    `cv_path` sert à construire le lien d'aperçu, mais cette fiche entière est
    déjà réservée à ADMIN/RH_MANAGER (`require_role` sur la route) : un
    candidat qui tenterait de consulter SA PROPRE fiche par ce chemin se
    heurte au même 401/403 que pour le reste de la page, avant même que le
    champ ne soit construit.

    Compte SANS 2FA (`avec_secrets=False`, le défaut) : on veut isoler le
    contrôle de rôle, pas retomber sur l'exigence de code TOTP.
    """
    user = await _compte(db)
    db.add(Candidate(user_id=user.id, full_name="Personne Test",
                     cv_path="/var/data/cv/profil/quelconque.pdf"))
    await db.commit()

    token = (await client.post("/api/v1/auth/login",
                               json={"email": user.email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    resp = await client.get(PROFIL.format(user.id),
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (401, 403)


# ── Accès ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_fiche_est_reservee_a_ladministration(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    assert (await client.get(PROFIL.format(user.id))).status_code in (401, 403)


@pytest.mark.asyncio
async def test_un_candidat_ne_consulte_pas_les_fiches(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    autre = await _compte(db)

    token = (await client.post("/api/v1/auth/login",
                               json={"email": autre.email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    resp = await client.get(PROFIL.format(user.id),
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_un_utilisateur_inconnu_rend_404(client: AsyncClient, db: AsyncSession):
    resp = await client.get(PROFIL.format(uuid.uuid4()),
                            headers=await _entete_admin(client, db))
    assert resp.status_code == 404


# ── La fiche d'un candidat ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_fiche_candidat_porte_son_dossier(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()

    assert corps["is_candidate"] is True
    assert corps["candidate"]["phone"] == "+216 20 000 000"
    assert corps["account"]["email"] == user.email
    assert len(corps["applications"]) == 1

    candidature = corps["applications"][0]
    assert candidature["job_title"] == "Développeur Laravel"
    assert candidature["cv_score"] == 68.0
    assert candidature["expected_salary"] == 2100
    assert candidature["status_label"] == "Test passé"


@pytest.mark.asyncio
async def test_la_fiche_porte_le_resume_du_test_pas_son_detail(
    client: AsyncClient, db: AsyncSession
):
    """
    Le détail des réponses se consulte depuis l'écran Test technique, qui
    l'accompagne de son contexte. Le recopier ici en ferait une seconde source
    à maintenir — et deux endroits qui divergent.
    """
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()

    test = corps["applications"][0]["test"]
    assert test["status"] == "TERMINE"
    assert test["score"] == 66.7
    assert test["correct_count"] == 2
    assert "answers" not in test
    assert "Question numéro" not in str(corps)


@pytest.mark.asyncio
async def test_le_composite_vient_avec_sa_completude(
    client: AsyncClient, db: AsyncSession
):
    """Deux composites de complétude différente ne se comparent pas."""
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()

    candidature = corps["applications"][0]
    assert candidature["composite_score"] == 71.5
    assert candidature["composite_completeness"] == 2


@pytest.mark.asyncio
async def test_les_compteurs_resument_le_dossier(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    user = await _candidat_complet(db, job)
    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()

    stats = corps["stats"]
    assert stats["applications"] == 1
    assert stats["tests_taken"] == 1
    assert stats["best_score"] == 68.0


@pytest.mark.asyncio
async def test_un_test_envoye_mais_jamais_rendu_ne_compte_pas(
    client: AsyncClient, db: AsyncSession
):
    """
    Un lien envoyé et jamais ouvert n'est pas un test passé. Les confondre
    gonflerait le compteur sans rien dire du candidat.
    """
    job = await _offre(db)
    user = await _compte(db)
    candidat = Candidate(user_id=user.id, full_name="Personne Test")
    db.add(candidat)
    await db.flush()
    app_ = Application(candidate_id=candidat.id, job_offer_id=job.id,
                       cv_file_path="/tmp/cv.pdf",
                       status=ApplicationStatus.TEST_SENT.value)
    db.add(app_)
    await db.flush()
    q = await svc.create_question(db, job.id, {
        "statement": "Une question du vivier ?",
        "options": ["A", "B"], "correct_answer": ["A"],
    })
    q.status = QuestionStatus.ACTIVE
    await db.commit()
    await svc.create_session(db, app_.id, [q.id])
    await db.commit()

    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()
    assert corps["stats"]["tests_taken"] == 0
    assert corps["applications"][0]["test"]["status"] == "ENVOYE"


# ── La fiche d'un compte interne ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_compte_interne_sarrete_a_son_compte(
    client: AsyncClient, db: AsyncSession
):
    """
    Un RH n'a pas de candidatures. Rendre des sections vides laisserait croire
    à une donnée manquante ou à une panne de chargement.
    """
    rh = await _compte(db, role=UserRole.RH)
    corps = (await client.get(PROFIL.format(rh.id),
                              headers=await _entete_admin(client, db))).json()

    assert corps["is_candidate"] is False
    assert corps["candidate"] is None
    assert corps["applications"] == []
    assert corps["account"]["role"] == UserRole.RH
    assert corps["stats"]["applications"] == 0


@pytest.mark.asyncio
async def test_un_candidat_sans_candidature_reste_un_candidat(
    client: AsyncClient, db: AsyncSession
):
    """Le dossier existe même vide : il n'a simplement pas encore postulé."""
    user = await _compte(db)
    db.add(Candidate(user_id=user.id, full_name="Personne Test"))
    await db.commit()

    corps = (await client.get(PROFIL.format(user.id),
                              headers=await _entete_admin(client, db))).json()
    assert corps["is_candidate"] is True
    assert corps["applications"] == []
    assert corps["stats"]["best_score"] is None


# ── Coût ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plusieurs_candidatures_ne_multiplient_pas_les_requetes(
    client: AsyncClient, db: AsyncSession
):
    """
    Écrite naïvement, cette fiche ferait une requête par candidature puis une
    par session. Ce test échoue si quelqu'un repasse à une boucle.
    """
    user = await _compte(db)
    candidat = Candidate(user_id=user.id, full_name="Personne Test")
    db.add(candidat)
    await db.flush()
    for i in range(6):
        job = await _offre(db, titre=f"Poste numéro {i}")
        db.add(Application(candidate_id=candidat.id, job_offer_id=job.id,
                           cv_file_path="/tmp/cv.pdf",
                           status=ApplicationStatus.PENDING.value))
    await db.commit()

    compteur = {"n": 0}
    from sqlalchemy import event
    from app.db.session import engine

    def _compter(*_a, **_k):
        compteur["n"] += 1

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _compter)
    try:
        corps = (await client.get(PROFIL.format(user.id),
                                  headers=await _entete_admin(client, db))).json()
    finally:
        event.remove(sync_engine, "before_cursor_execute", _compter)

    assert len(corps["applications"]) == 6
    # Large volontairement : on surveille un ORDRE DE GRANDEUR, pas un nombre
    # exact que le moindre ajout ferait échouer à tort.
    assert compteur["n"] < 25, f"{compteur['n']} requêtes pour 6 candidatures"
