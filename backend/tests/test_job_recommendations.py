"""
Recommandation d'offres au candidat — matching inverse candidat → offres.

Pipeline testé (cf. `app/services/recommendation_service.py`) :
CV analysé → embedding indexé → recherche vectorielle → contraintes métier
→ score de compatibilité pondéré par l'offre → seuil → recommandations.

Ce que ces tests verrouillent, scénario par scénario :

  A. CV très compatible                 → recommandé
  B. CV peu compatible                  → écarté par le seuil
  C. Contrainte obligatoire non tenue   → écarté MALGRÉ une sémantique forte
  D. Aucune offre compatible            → liste vide, pas d'erreur
  E. Plusieurs offres compatibles       → triées par score décroissant
  F. Candidat sans CV analysé           → liste vide, pas de 500
  G. Offre aux critères absents         → le moteur ne plante pas
  H. Sens direct offre → candidats      → inchangé (voir test_semantic.py)

Le backend d'embedding est forcé sur `hash` : déterministe, hors-ligne, et
surtout il ne télécharge pas 480 Mo de poids au premier appel. Le pipeline
testé est le même — seule la façon de produire les vecteurs change.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CVAnalysis
from app.models.user import User
from app.services.recommendation_service import recommendation_service
from app.services.semantic_service import semantic_service
from tests.conftest import VALID_PASSWORD

# Profil de référence : développeuse backend Python confirmée.
CV_PYTHON = {
    "skills": ["python", "fastapi", "postgresql", "docker", "git", "rest"],
    "annees": 5.0,
    "formation": "MASTER",
    "texte": ("Developpeuse backend Python. API REST FastAPI, PostgreSQL, "
              "Docker, microservices, tests automatises, CI/CD."),
}


@pytest.fixture(autouse=True)
def _backend_hash(monkeypatch):
    """Embeddings déterministes et hors-ligne pour tout le module."""
    from app.services.embedding_service import embedding_service
    monkeypatch.setattr(embedding_service, "_model_failed", True)
    monkeypatch.setattr(embedding_service, "_model", None)
    yield


async def _candidat(client: AsyncClient, db: AsyncSession) -> tuple[User, str]:
    suffixe = uuid.uuid4().hex[:8]
    email = f"reco_{suffixe}@example.com"
    user = User(
        id=uuid.uuid4(), email=email, username=f"reco_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="Candidat Reco",
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": VALID_PASSWORD})
    return user, resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _offre(db: AsyncSession, titre: str, description: str, **champs) -> JobOffer:
    job = JobOffer(
        title=titre, description=description,
        required_skills=champs.get("skills", []),
        required_experience_years=champs.get("annees"),
        required_education_level=champs.get("formation"),
        is_active=True, status=champs.get("status", "PUBLISHED"),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    await semantic_service.index_job(db, job)
    await db.commit()
    return job


async def _profil_cv(
    db: AsyncSession, user: User, *, skills: list[str], annees: float | None,
    formation: str | None, texte: str,
) -> Candidate:
    """
    Candidat + CV analysé et indexé, comme le ferait le scoring agent.

    L'analyse est rattachée à une candidature « support » sur une offre
    fermée : c'est la contrainte du modèle (CVAnalysis.application_id est
    obligatoire), et une offre fermée n'interfère pas avec les
    recommandations, qui ne portent que sur les offres publiées.
    """
    candidate = Candidate(user_id=user.id, full_name=user.full_name)
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    support = JobOffer(title="Offre support (fermée)", description="Support de test.",
                       is_active=True, status="CLOSED")
    db.add(support)
    await db.commit()
    await db.refresh(support)

    app = Application(candidate_id=candidate.id, job_offer_id=support.id,
                      cv_file_path="uploads/cvs/test.pdf", status="PENDING")
    db.add(app)
    await db.commit()
    await db.refresh(app)

    analysis = CVAnalysis(
        application_id=app.id, candidate_id=candidate.id, is_parsed=True,
        extracted_skills=skills, extracted_experience_years=annees,
        extracted_education_level=formation, raw_text=texte,
    )
    db.add(analysis)
    await db.commit()
    await semantic_service.index_cv(db, analysis)
    await db.commit()
    return candidate


async def _recommander(db: AsyncSession, candidate: Candidate, limit: int = 6):
    return await recommendation_service.recommend_for_candidate(
        db, candidate.id, limit=limit)


# ── A. CV très compatible ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_cv_tres_compatible_est_recommande(client: AsyncClient, db: AsyncSession):
    user, _ = await _candidat(client, db)
    cible = await _offre(
        db, "Développeur Python Backend",
        "Développement d'API REST en Python avec FastAPI, PostgreSQL et Docker.",
        skills=["python", "fastapi", "postgresql", "docker"], annees=3,
        formation="BACHELOR",
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)

    assert [r["job_id"] for r in resultats] == [cible.id]
    reco = resultats[0]
    assert reco["compatibility_score"] >= settings.RECOMMENDATION_THRESHOLD
    assert set(reco["matching_skills"]) == {"python", "fastapi", "postgresql", "docker"}
    assert reco["missing_skills"] == []
    assert reco["reasons"], "une recommandation doit pouvoir s'expliquer"


# ── B. CV peu compatible ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b_cv_peu_compatible_est_ecarte(client: AsyncClient, db: AsyncSession):
    user, _ = await _candidat(client, db)
    await _offre(
        db, "Chef pâtissier",
        "Confection de desserts, viennoiseries, gestion des stocks de farine.",
        skills=["pâtisserie", "viennoiserie", "chocolat"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    assert await _recommander(db, candidate) == []


# ── C. Contrainte obligatoire non respectée ───────────────────────────────────

@pytest.mark.asyncio
async def test_c_experience_insuffisante_exclut_malgre_semantique_forte(
    client: AsyncClient, db: AsyncSession,
):
    """
    Le cœur de la règle métier : l'offre est le jumeau exact du CV côté
    compétences et vocabulaire — seule l'ancienneté exigée est hors de
    portée. Elle ne doit pas être recommandée.
    """
    user, _ = await _candidat(client, db)
    await _offre(
        db, "Développeur Python Backend Senior",
        "Développement d'API REST en Python avec FastAPI, PostgreSQL et Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
        annees=8,  # le candidat en a 1
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": 1.0,
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    assert await _recommander(db, candidate) == []


@pytest.mark.asyncio
async def test_c_bis_niveau_etudes_insuffisant_exclut(
    client: AsyncClient, db: AsyncSession,
):
    user, _ = await _candidat(client, db)
    await _offre(
        db, "Développeur Python Backend",
        "Développement d'API REST en Python avec FastAPI, PostgreSQL et Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
        formation="PHD",  # le candidat est au bac
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": "HIGH_SCHOOL", "texte": CV_PYTHON["texte"]})

    assert await _recommander(db, candidate) == []


@pytest.mark.asyncio
async def test_c_ter_donnee_absente_nexclut_pas(client: AsyncClient, db: AsyncSession):
    """
    Une expérience NON DÉTECTÉE n'est pas une expérience nulle : exclure sur
    une lecture ratée punirait le candidat pour une limite de l'outil.
    """
    user, _ = await _candidat(client, db)
    cible = await _offre(
        db, "Développeur Python Backend",
        "Développement d'API REST en Python avec FastAPI, PostgreSQL et Docker.",
        skills=["python", "fastapi", "postgresql", "docker"], annees=3,
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": None,  # non détectée
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)
    assert [r["job_id"] for r in resultats] == [cible.id], (
        "l'offre doit rester éligible quand l'expérience n'a pas pu être lue"
    )


# ── D. Aucune offre compatible ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_d_aucune_offre_ouverte_renvoie_liste_vide(
    client: AsyncClient, db: AsyncSession,
):
    user, _ = await _candidat(client, db)
    await _offre(
        db, "Développeur Python (brouillon)",
        "Développement d'API REST en Python avec FastAPI, PostgreSQL et Docker.",
        skills=["python", "fastapi"], status="DRAFT",
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    assert await _recommander(db, candidate) == []


# ── E. Classement par score décroissant ───────────────────────────────────────

@pytest.mark.asyncio
async def test_e_plusieurs_offres_triees_par_score_decroissant(
    client: AsyncClient, db: AsyncSession,
):
    user, _ = await _candidat(client, db)
    parfaite = await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker microservices.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    partielle = await _offre(
        db, "Développeur Python Data",
        "Traitement de données en Python, PostgreSQL, ETL et reporting.",
        skills=["python", "postgresql", "pandas", "airflow"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)
    scores = [r["compatibility_score"] for r in resultats]

    assert scores == sorted(scores, reverse=True), "tri par compatibilité décroissante"
    assert resultats[0]["job_id"] == parfaite.id
    ids = [r["job_id"] for r in resultats]
    if partielle.id in ids:
        # Couverture partielle ⇒ compétences manquantes explicitement listées.
        partielle_reco = next(r for r in resultats if r["job_id"] == partielle.id)
        assert partielle_reco["missing_skills"]


# ── F. Candidat sans CV analysé ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_f_candidat_sans_cv_analyse(client: AsyncClient, db: AsyncSession):
    user, token = await _candidat(client, db)
    await _offre(db, "Développeur Python", "API REST Python FastAPI.",
                 skills=["python"])
    candidate = Candidate(user_id=user.id, full_name=user.full_name)
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    assert await _recommander(db, candidate) == []

    # Et par l'API : surtout pas de 500.
    resp = await client.get("/api/v1/recruitment/me/recommended-jobs",
                            headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"recommendations": []}


# ── G. Offre aux critères optionnels absents ──────────────────────────────────

@pytest.mark.asyncio
async def test_g_offre_sans_criteres_ne_plante_pas(client: AsyncClient, db: AsyncSession):
    """Ni compétences, ni ancienneté, ni formation exigées : rien ne casse."""
    user, _ = await _candidat(client, db)
    nue = await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker microservices.",
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)
    assert [r["job_id"] for r in resultats] == [nue.id]
    assert resultats[0]["matching_skills"] == []
    assert resultats[0]["missing_skills"] == []
    assert resultats[0]["reasons"]


@pytest.mark.asyncio
async def test_g_bis_cv_sans_competences_ne_plante_pas(
    client: AsyncClient, db: AsyncSession,
):
    user, _ = await _candidat(client, db)
    await _offre(db, "Développeur Python", "API REST Python FastAPI.",
                 skills=["python", "fastapi"])
    candidate = await _profil_cv(db, user, skills=[], annees=None,
                                 formation=None, texte="Curriculum vitae.")

    assert await _recommander(db, candidate) == []  # 0 compétence ⇒ sous le seuil


# ── Contrat d'API ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_forme_de_la_reponse(client: AsyncClient, db: AsyncSession):
    user, token = await _candidat(client, db)
    await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resp = await client.get("/api/v1/recruitment/me/recommended-jobs",
                            headers=_auth(token))
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert "recommendations" in corps and corps["recommendations"]
    premiere = corps["recommendations"][0]
    for champ in ("job_id", "title", "compatibility_score",
                  "matching_skills", "missing_skills", "reasons"):
        assert champ in premiere, f"champ absent du contrat : {champ}"
    assert 0.0 <= premiere["compatibility_score"] <= 1.0


@pytest.mark.asyncio
async def test_api_sans_authentification_refuse(client: AsyncClient):
    resp = await client.get("/api/v1/recruitment/me/recommended-jobs")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_route_rh_est_protegee(client: AsyncClient, db: AsyncSession):
    """La route back-office reste derrière la permission `semantic:read`."""
    _, token = await _candidat(client, db)
    resp = await client.get(
        f"/api/v1/semantic/candidates/{uuid.uuid4()}/recommendations",
        headers=_auth(token))
    assert resp.status_code == 403


# ── Offres déjà postulées ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_offre_deja_postulee_nest_pas_recommandee(
    client: AsyncClient, db: AsyncSession,
):
    user, _ = await _candidat(client, db)
    cible = await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})
    assert [r["job_id"] for r in await _recommander(db, candidate)] == [cible.id]

    db.add(Application(candidate_id=candidate.id, job_offer_id=cible.id,
                       cv_file_path="uploads/cvs/test.pdf", status="PENDING"))
    await db.commit()

    assert await _recommander(db, candidate) == []


# ── Reranking (câblage) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reranker_est_utilise_quand_active(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    """
    Le cross-encoder est désactivé par défaut (modèle de ~2,3 Go). On vérifie
    ici le CÂBLAGE avec un faux reranker : s'il répond, ses scores remplacent
    le cosinus dans la part sémantique.
    """
    appels: list[int] = []

    class FauxReranker:
        def predict(self, paires):
            appels.append(len(paires))
            return [5.0] * len(paires)  # logit élevé → sigmoïde ≈ 0.993

    monkeypatch.setattr(settings, "RERANKER_ENABLED", True)
    monkeypatch.setattr(recommendation_service, "_reranker", FauxReranker())
    monkeypatch.setattr(recommendation_service, "_reranker_failed", False)

    user, _ = await _candidat(client, db)
    await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)
    assert appels, "le reranker doit être sollicité quand il est activé"
    assert resultats and resultats[0]["compatibility_score"] > 0.9


@pytest.mark.asyncio
async def test_reranker_en_panne_ne_casse_rien(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    """Un reranker qui échoue dégrade le classement, il ne casse pas la page."""
    class RerankerCasse:
        def predict(self, paires):
            raise RuntimeError("modèle indisponible")

    monkeypatch.setattr(settings, "RERANKER_ENABLED", True)
    monkeypatch.setattr(recommendation_service, "_reranker", RerankerCasse())
    monkeypatch.setattr(recommendation_service, "_reranker_failed", False)

    user, _ = await _candidat(client, db)
    cible = await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    resultats = await _recommander(db, candidate)
    assert [r["job_id"] for r in resultats] == [cible.id]


# ── Seuil configurable ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seuil_configurable_filtre_reellement(
    client: AsyncClient, db: AsyncSession, monkeypatch,
):
    user, _ = await _candidat(client, db)
    await _offre(
        db, "Développeur Python Backend",
        "API REST Python FastAPI PostgreSQL Docker.",
        skills=["python", "fastapi", "postgresql", "docker"],
    )
    candidate = await _profil_cv(db, user, **{
        "skills": CV_PYTHON["skills"], "annees": CV_PYTHON["annees"],
        "formation": CV_PYTHON["formation"], "texte": CV_PYTHON["texte"]})

    assert await _recommander(db, candidate), "recommandée au seuil par défaut"

    monkeypatch.setattr(settings, "RECOMMENDATION_THRESHOLD", 0.999)
    assert await _recommander(db, candidate) == [], "écartée si le seuil monte"
