"""
Le détail de score, vu par le candidat.

Trois garanties, et la troisième est celle qui demande le plus d'attention :

1. **On ne voit que sa propre candidature.** La propriété est vérifiée, pas
   seulement l'authentification — sinon il suffirait de changer l'identifiant
   dans l'URL pour lire le dossier d'un autre.
2. **Les formulations internes ne fuient jamais.** « Candidature non
   recommandée » est un conseil adressé au recruteur ; sur l'écran du candidat,
   il se lirait comme un refus.
3. **Ce qui est caché est INVISIBLE, pas grisé.** Tant que le RH n'a pas ouvert
   le partage, la note de test est absente de la réponse — pas à `null`. Un
   `null` accompagné d'un libellé apprendrait au candidat qu'il existe une note
   qu'on lui refuse, et transformerait chaque candidature en demande de partage.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.application_status import ApplicationStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.models.user import User, UserRole

from tests.conftest import VALID_PASSWORD

DETAIL = "/api/v1/recruitment/my-applications/{}/score-detail"
VISIBILITE = "/api/v1/assessment/applications/{}/visibility"


async def _offre(db: AsyncSession) -> JobOffer:
    job = JobOffer(
        title="Développeur Laravel – Backend",
        description="Poste backend PHP.",
        required_skills=["Laravel", "PHP", "SQL", "PostgreSQL"],
        required_experience_years=3, required_education_level="BACHELOR",
        salary_min=1800, salary_max=2600,
        is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def _candidat(db: AsyncSession, job: JobOffer, *, avec_score=True):
    suffixe = uuid.uuid4().hex[:8]
    email = f"c_{suffixe}@example.com"
    user = User(email=email, username=f"c_{suffixe}",
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

    if avec_score:
        db.add(CandidateScore(
            application_id=app_.id, job_offer_id=job.id, candidate_id=candidat.id,
            total_score=62.0, skills_score=50.0, experience_score=66.0,
            education_score=100.0,
            score_details={
                "matched_skills": ["laravel", "php"],
                "missing_skills": ["sql", "postgresql"],
                "required_skills": ["laravel", "php", "sql", "postgresql"],
                "extracted_years": 2.0,
                "required_years": 3.0,
                "extracted_education": "BACHELOR",
                "required_education": "BACHELOR",
                "weights": {"skills": 0.5, "experience": 0.3, "education": 0.2},
                "strengths": ["Compétences partiellement compatibles (2 sur 4)"],
                "weaknesses": ["Expérience insuffisante (2 ans, 3 ans requis)"],
                "recommendation": ("Profil partiellement compatible. "
                                   "Candidature à considérer avec réserves."),
            },
            test_score=71.0,
            interview_notes="Hésitant sur les jointures. À creuser.",
        ))
    await db.commit()
    await db.refresh(app_)
    return app_, email


async def _entete(client: AsyncClient, email: str) -> dict[str, str]:
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _entete_rh(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
                hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
                role=UserRole.ADMIN, is_active=True, is_verified=True))
    await db.commit()
    return await _entete(client, email)


# ── Propriété ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_candidat_voit_sa_propre_candidature(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_, email = await _candidat(db, job)

    resp = await client.get(DETAIL.format(app_.id),
                            headers=await _entete(client, email))
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["job_title"] == "Développeur Laravel – Backend"
    assert corps["score"] == 62.0


@pytest.mark.asyncio
async def test_un_candidat_ne_voit_pas_celle_dun_autre(
    client: AsyncClient, db: AsyncSession
):
    """
    Le contrôle qui compte : il ne suffit pas d'être connecté. Sans vérification
    de propriété, changer l'identifiant dans l'URL ouvrirait le dossier du
    voisin — CV, score et retours compris.
    """
    job = await _offre(db)
    app_autre, _ = await _candidat(db, job)
    _, mon_email = await _candidat(db, job)

    resp = await client.get(DETAIL.format(app_autre.id),
                            headers=await _entete(client, mon_email))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_une_candidature_inconnue_rend_le_meme_404(
    client: AsyncClient, db: AsyncSession
):
    """
    Même réponse que « pas la vôtre » : les distinguer permettrait d'énumérer
    les candidatures des autres par essais successifs.
    """
    job = await _offre(db)
    _, email = await _candidat(db, job)
    resp = await client.get(DETAIL.format(uuid.uuid4()),
                            headers=await _entete(client, email))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sans_authentification_rien(client: AsyncClient, db: AsyncSession):
    job = await _offre(db)
    app_, _ = await _candidat(db, job)
    assert (await client.get(DETAIL.format(app_.id))).status_code in (401, 403)


# ── Ce qui ne doit jamais fuiter ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_les_formulations_internes_ne_fuitent_pas(
    client: AsyncClient, db: AsyncSession
):
    """
    Le moteur écrit POUR LE RH, à propos du candidat. « Candidature à
    considérer avec réserves » est un conseil au recruteur ; affiché à
    l'intéressé, il se lit comme un refus.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    brut = (await client.get(DETAIL.format(app_.id),
                             headers=await _entete(client, email))).text

    for interdit in ("recommandée", "réserves", "insuffisante",
                     "peu compatible", "Profil"):
        assert interdit not in brut, f"« {interdit} » a fuité vers le candidat"


@pytest.mark.asyncio
async def test_les_notes_dentretien_internes_ne_fuitent_jamais(
    client: AsyncClient, db: AsyncSession
):
    """
    `interview_notes` est un carnet de bord, pas un message. Même partage
    ouvert, il ne sort pas : seul `candidate_feedback`, écrit dans cette
    intention, est partageable.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    entete_rh = await _entete_rh(client, db)

    await client.post(VISIBILITE.format(app_.id), headers=entete_rh,
                      json={"interview_feedback_visible": True})

    brut = (await client.get(DETAIL.format(app_.id),
                             headers=await _entete(client, email))).text
    assert "Hésitant sur les jointures" not in brut


# ── Le partage, fermé par défaut ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_note_de_test_est_absente_par_defaut(
    client: AsyncClient, db: AsyncSession
):
    """
    ABSENTE, pas à `null`. C'est tout l'objet de la règle : un champ nul
    accompagné d'un libellé apprendrait au candidat qu'il existe une note qu'on
    lui refuse, et le pousserait à la réclamer.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job)

    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert "test_score" not in corps
    assert "interview_feedback" not in corps


@pytest.mark.asyncio
async def test_le_rh_peut_ouvrir_la_note_de_test(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    entete_rh = await _entete_rh(client, db)

    ouvert = await client.post(VISIBILITE.format(app_.id), headers=entete_rh,
                               json={"test_score_visible": True})
    assert ouvert.status_code == 200, ouvert.text
    assert ouvert.json()["test_score_visible"] is True

    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert corps["test_score"] == 71.0


@pytest.mark.asyncio
async def test_le_rh_peut_refermer(client: AsyncClient, db: AsyncSession):
    """Un partage doit pouvoir être repris — une erreur d'un clic se corrige."""
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    entete_rh = await _entete_rh(client, db)

    await client.post(VISIBILITE.format(app_.id), headers=entete_rh,
                      json={"test_score_visible": True})
    await client.post(VISIBILITE.format(app_.id), headers=entete_rh,
                      json={"test_score_visible": False})

    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert "test_score" not in corps


@pytest.mark.asyncio
async def test_un_retour_partage_atteint_le_candidat(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    entete_rh = await _entete_rh(client, db)

    await client.post(VISIBILITE.format(app_.id), headers=entete_rh, json={
        "candidate_feedback": "Entretien très clair sur la partie métier.",
        "interview_feedback_visible": True,
    })

    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert corps["interview_feedback"] == "Entretien très clair sur la partie métier."


@pytest.mark.asyncio
async def test_ouvrir_un_retour_vide_ne_leve_pas_de_drapeau(
    client: AsyncClient, db: AsyncSession
):
    """
    Un drapeau levé sur du vide ne montrerait rien au candidat et laisserait
    croire au RH qu'il a partagé quelque chose.
    """
    job = await _offre(db)
    app_, _ = await _candidat(db, job)
    entete_rh = await _entete_rh(client, db)

    resp = await client.post(VISIBILITE.format(app_.id), headers=entete_rh,
                             json={"interview_feedback_visible": True})
    assert resp.json()["interview_feedback_visible"] is False


@pytest.mark.asyncio
async def test_la_visibilite_est_reservee_au_rh(client: AsyncClient, db: AsyncSession):
    """Un candidat ne doit évidemment pas pouvoir s'ouvrir le partage."""
    job = await _offre(db)
    app_, email = await _candidat(db, job)

    resp = await client.post(VISIBILITE.format(app_.id),
                             headers=await _entete(client, email),
                             json={"test_score_visible": True})
    assert resp.status_code in (401, 403)


# ── Le contenu utile ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_detail_porte_les_competences_des_deux_cotes(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()

    assert set(corps["skills_matched"]) == {"laravel", "php"}
    assert set(corps["skills_missing"]) == {"sql", "postgresql"}
    assert corps["weights"]["skills"] == 0.5


@pytest.mark.asyncio
async def test_les_observations_constatent_sans_juger(
    client: AsyncClient, db: AsyncSession
):
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()

    sujets = {o["sujet"] for o in corps["observations"]}
    assert {"Compétences", "Expérience"} <= sujets

    texte = " ".join(o["constat"] for o in corps["observations"])
    assert "2 ont été reconnues" in texte or "2 ont été reconnues" in texte
    # Les deux chiffres sont donnés côte à côte : le candidat situe l'écart
    # lui-même, au lieu de lire un jugement sur cet écart.
    assert "3 an(s) d'expérience" in texte and "2 dans votre CV" in texte


@pytest.mark.asyncio
async def test_les_conseils_nencouragent_pas_le_bourrage_de_mots_cles(
    client: AsyncClient, db: AsyncSession
):
    """
    « Ajoutez ces mots » enseignerait la triche. « Si vous le pratiquez, rendez-le
    visible » invite à se situer.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()

    texte = " ".join(corps["advice"])
    assert "si vous pratiquez" in texte.lower()
    assert "ajoutez" not in texte.lower()
    # Et la phrase qui désamorce l'essentiel des malentendus.
    assert "examinée par un recruteur" in texte


@pytest.mark.asyncio
async def test_la_limite_de_la_correspondance_est_annoncee(
    client: AsyncClient, db: AsyncSession
):
    """
    « PostgreSQL » ne vaut pas « SQL » pour la machine. Le taire ferait passer
    l'outil pour incapable de lire le CV qu'on vient de lui confier.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job)
    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert "telles qu'elles y sont nommées" in " ".join(corps["advice"])


@pytest.mark.asyncio
async def test_sans_analyse_la_page_le_dit(client: AsyncClient, db: AsyncSession):
    """
    Le scoring tourne en tâche de fond au dépôt. Avant qu'il ait fini, afficher
    zéro se lirait comme une note catastrophique.
    """
    job = await _offre(db)
    app_, email = await _candidat(db, job, avec_score=False)

    corps = (await client.get(DETAIL.format(app_.id),
                              headers=await _entete(client, email))).json()
    assert corps["analysis_ready"] is False
    assert corps["job_title"]
    assert "score" not in corps or corps.get("score") is None
