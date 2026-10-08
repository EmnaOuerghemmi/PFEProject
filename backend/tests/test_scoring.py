"""
Tests du moteur de scoring — le cœur métier de la plateforme.

Ce module décide du classement des candidats. Une régression y serait
particulièrement coûteuse car SILENCIEUSE : les scores deviendraient faux
sans qu'aucune erreur ne remonte, et des décisions de recrutement seraient
prises sur des données erronées.

Organisation :
  1. Calculs purs (compétences, expérience, formation, pondération)
  2. Génération du rapport (recommandations)
  3. Persistance et classement (base de données)
  4. Contrôle d'accès de l'API
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore, CVAnalysis
from app.models.user import User
from app.services.scoring_service import ScoringService, scoring_service

from tests.conftest import SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD


# ══════════════════════════════════════════════════════════════════════════
#  1. CALCUL DU SCORE DE COMPÉTENCES
# ══════════════════════════════════════════════════════════════════════════

def test_skills_score_sans_exigence_vaut_100():
    """Une offre sans compétence requise ne doit pénaliser personne."""
    assert ScoringService.compute_skills_score(None, ["python"]) == 100.0
    assert ScoringService.compute_skills_score([], ["python"]) == 100.0


def test_skills_score_correspondance_totale():
    assert ScoringService.compute_skills_score(
        ["Python", "Django"], ["python", "django"]
    ) == 100.0


def test_skills_score_correspondance_partielle_est_proportionnelle():
    """2 compétences requises, 1 maîtrisée -> 50 %."""
    assert ScoringService.compute_skills_score(
        ["Python", "Django"], ["python"]
    ) == 50.0


def test_skills_score_aucune_correspondance():
    assert ScoringService.compute_skills_score(["Python"], ["cobol"]) == 0.0


def test_skills_score_insensible_a_la_casse():
    assert ScoringService.compute_skills_score(["PYTHON"], ["Python"]) == 100.0


def test_skills_score_cv_sans_competence_extraite():
    assert ScoringService.compute_skills_score(["Python"], []) == 0.0


@pytest.mark.parametrize(
    "requises",
    [
        ["node.js", "react.js"],   # forme pointée
        ["nodejs", "reactjs"],     # forme accolée
        ["Node JS", "React"],      # forme espacée
    ],
)
def test_skills_score_independant_de_l_ecriture(requises):
    """
    RÉGRESSION : trois écritures d'une même exigence doivent produire le même
    score. La forme « reactjs » était auparavant absente du vocabulaire NLP et
    silencieusement ignorée : l'offre ne réclamait plus que Node, et un
    candidat ne connaissant pas React obtenait 100 % au lieu de 50 %.
    """
    assert ScoringService.compute_skills_score(requises, ["node"]) == 50.0


def test_skills_score_competence_hors_vocabulaire_reste_exigee():
    """
    Une compétence inconnue du vocabulaire NLP ne doit pas disparaître :
    sinon l'exigence s'évapore et le score est surévalué.
    """
    requises = ["Python", "FrameworkMaisonInterne"]
    canoniques = ScoringService._canonical_required_skills(requises)
    assert len(canoniques) == 2, f"une exigence a été perdue : {canoniques}"
    assert ScoringService.compute_skills_score(requises, ["python"]) == 50.0


# ══════════════════════════════════════════════════════════════════════════
#  2. CALCUL DU SCORE D'EXPÉRIENCE
# ══════════════════════════════════════════════════════════════════════════

def test_experience_sans_exigence_vaut_100():
    assert ScoringService.compute_experience_score(None, None) == 100.0
    assert ScoringService.compute_experience_score(0, None) == 100.0


def test_experience_suffisante_vaut_100():
    assert ScoringService.compute_experience_score(3, 5) == 100.0
    assert ScoringService.compute_experience_score(3, 3) == 100.0


def test_experience_non_detectee_vaut_0():
    """Exigence posée mais CV muet : on ne suppose rien en faveur du candidat."""
    assert ScoringService.compute_experience_score(3, None) == 0.0


def test_experience_insuffisante_est_proportionnelle():
    assert ScoringService.compute_experience_score(4, 2) == 50.0
    assert ScoringService.compute_experience_score(10, 1) == 10.0


# ══════════════════════════════════════════════════════════════════════════
#  3. CALCUL DU SCORE DE FORMATION
# ══════════════════════════════════════════════════════════════════════════

def test_education_sans_exigence_vaut_100():
    assert ScoringService.compute_education_score(None, "NONE") == 100.0
    assert ScoringService.compute_education_score("NONE", "NONE") == 100.0


def test_education_niveau_superieur_vaut_100():
    assert ScoringService.compute_education_score("BACHELOR", "PHD") == 100.0


def test_education_niveau_equivalent_vaut_100():
    assert ScoringService.compute_education_score("MASTER", "MASTER") == 100.0


def test_ingenieur_equivaut_a_master():
    """Les deux valent 3 dans le barème : un ingénieur satisfait un master."""
    assert ScoringService.compute_education_score("MASTER", "INGENIEUR") == 100.0
    assert ScoringService.compute_education_score("INGENIEUR", "MASTER") == 100.0


def test_education_insuffisante_est_proportionnelle():
    """BACHELOR (2) pour un PHD (4) requis -> 50 %."""
    assert ScoringService.compute_education_score("PHD", "BACHELOR") == 50.0


def test_education_niveau_inconnu_traite_comme_absent():
    """Une valeur non répertoriée ne doit pas faire planter le calcul."""
    assert ScoringService.compute_education_score("MASTER", "DIPLOME_EXOTIQUE") == 0.0


# ══════════════════════════════════════════════════════════════════════════
#  4. PONDÉRATION DU SCORE TOTAL
# ══════════════════════════════════════════════════════════════════════════

def test_total_score_pondere_selon_les_poids():
    """100/0/0 avec les poids par défaut (0.5 / 0.3 / 0.2) -> 50."""
    assert ScoringService.compute_total_score(100, 0, 0) == 50.0
    assert ScoringService.compute_total_score(0, 100, 0) == pytest.approx(30.0)
    assert ScoringService.compute_total_score(0, 0, 100) == pytest.approx(20.0)


def test_total_score_parfait():
    assert ScoringService.compute_total_score(100, 100, 100) == 100.0


def test_total_score_normalise_des_poids_qui_ne_somment_pas_a_1():
    """
    Les poids sont saisis librement par le recruteur. 1/1/1 doit donner une
    moyenne simple, pas un score de 300.
    """
    total = ScoringService.compute_total_score(90, 60, 30, 1, 1, 1)
    assert total == pytest.approx(60.0)


def test_total_score_poids_tous_nuls_ne_divise_pas_par_zero():
    assert ScoringService.compute_total_score(100, 100, 100, 0, 0, 0) == 0.0


def test_total_score_plafonne_a_100():
    assert ScoringService.compute_total_score(100, 100, 100, 5, 5, 5) <= 100.0


def test_poids_privilegiant_les_competences():
    """Un recruteur ne pesant que les compétences doit obtenir ce score-là."""
    total = ScoringService.compute_total_score(
        80, 0, 0, weight_skills=1.0, weight_experience=0.0, weight_education=0.0
    )
    assert total == pytest.approx(80.0)


# ══════════════════════════════════════════════════════════════════════════
#  5. RAPPORT ET RECOMMANDATION
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "score,extrait_attendu",
    [
        (95, "fortement recommandée"),
        (70, "Candidature recommandée"),
        (50, "réserves"),
        (20, "non recommandée"),
    ],
)
def test_recommandation_suit_les_seuils(score, extrait_attendu):
    """Seuils 80 / 60 / 40 : la formulation doit basculer au bon endroit."""
    _, _, recommandation = ScoringService._generate_report(
        total_score=score, skills_score=score, experience_score=score,
        education_score=score, matched_skills=["python"], missing_skills=[],
        extracted_years=3, required_years=2,
        extracted_education="MASTER", required_education="BACHELOR",
    )
    assert extrait_attendu in recommandation


def test_rapport_liste_les_competences_manquantes():
    _, faiblesses, _ = ScoringService._generate_report(
        total_score=40, skills_score=33, experience_score=50, education_score=50,
        matched_skills=["python"], missing_skills=["django", "fastapi"],
        extracted_years=1, required_years=3,
        extracted_education="BACHELOR", required_education="MASTER",
    )
    texte = " ".join(faiblesses)
    assert "django" in texte and "fastapi" in texte


def test_rapport_signale_une_experience_non_detectable():
    _, faiblesses, _ = ScoringService._generate_report(
        total_score=50, skills_score=100, experience_score=0, education_score=100,
        matched_skills=["python"], missing_skills=[],
        extracted_years=None, required_years=3,
        extracted_education="MASTER", required_education="MASTER",
    )
    assert any("non détectable" in f for f in faiblesses)


# ══════════════════════════════════════════════════════════════════════════
#  6. PERSISTANCE ET CLASSEMENT
# ══════════════════════════════════════════════════════════════════════════

async def _creer_contexte(db: AsyncSession, **champs_offre):
    """Crée un utilisateur, un candidat, une offre et une candidature liés."""
    suffixe = uuid.uuid4().hex[:8]
    user = User(
        email=f"cand_{suffixe}@example.com",
        username=f"cand_{suffixe}",
        hashed_password="x",
        full_name="Candidat Test",
    )
    db.add(user)
    await db.flush()

    candidate = Candidate(user_id=user.id, full_name="Candidat Test")
    db.add(candidate)

    offre = JobOffer(
        title="Développeur Full Stack",
        description="Poste de test",
        required_skills=champs_offre.get("required_skills", ["Python", "Django"]),
        required_experience_years=champs_offre.get("required_experience_years", 3),
        required_education_level=champs_offre.get("required_education_level", "BACHELOR"),
        weight_skills=champs_offre.get("weight_skills", 0.5),
        weight_experience=champs_offre.get("weight_experience", 0.3),
        weight_education=champs_offre.get("weight_education", 0.2),
    )
    db.add(offre)
    await db.flush()

    application = Application(
        candidate_id=candidate.id,
        job_offer_id=offre.id,
        cv_file_path="/tmp/cv.pdf",
        status="PENDING",
    )
    db.add(application)
    await db.flush()
    return candidate, offre, application


def _analyse(candidate_id, application_id, competences, annees, niveau):
    return CVAnalysis(
        application_id=application_id,
        candidate_id=candidate_id,
        extracted_skills=competences,
        extracted_experience_years=annees,
        extracted_education_level=niveau,
        is_parsed=True,
    )


@pytest.mark.asyncio
async def test_compute_and_store_cree_un_score_complet(db: AsyncSession):
    candidate, offre, application = await _creer_contexte(db)
    analyse = _analyse(candidate.id, application.id, ["python", "django"], 5, "MASTER")

    score = await scoring_service.compute_and_store_score(
        db, application.id, offre.id, candidate.id, analyse, offre
    )

    # Profil idéal : toutes les composantes au maximum.
    assert score.skills_score == 100.0
    assert score.experience_score == 100.0
    assert score.education_score == 100.0
    assert score.total_score == 100.0
    assert score.score_details["matched_skills"] == ["django", "python"]
    assert score.score_details["missing_skills"] == []
    assert "fortement recommandée" in score.score_details["recommendation"]


@pytest.mark.asyncio
async def test_compute_and_store_est_idempotent(db: AsyncSession):
    """
    Relancer l'analyse d'une candidature doit METTRE À JOUR le score existant.
    Un doublon violerait la contrainte d'unicité sur application_id et
    fausserait le classement.
    """
    candidate, offre, application = await _creer_contexte(db)

    analyse1 = _analyse(candidate.id, application.id, ["python"], 1, "HIGH_SCHOOL")
    premier = await scoring_service.compute_and_store_score(
        db, application.id, offre.id, candidate.id, analyse1, offre
    )
    premier_id, premier_total = premier.id, premier.total_score

    # Le CV est ré-analysé et se révèle bien meilleur.
    analyse2 = _analyse(candidate.id, application.id, ["python", "django"], 5, "MASTER")
    second = await scoring_service.compute_and_store_score(
        db, application.id, offre.id, candidate.id, analyse2, offre
    )

    assert second.id == premier_id, "un second enregistrement a été créé"
    assert second.total_score > premier_total

    from sqlalchemy import select, func
    total = await db.scalar(
        select(func.count(CandidateScore.id)).where(
            CandidateScore.application_id == application.id
        )
    )
    assert total == 1


@pytest.mark.asyncio
async def test_score_partiel_reflete_les_manques(db: AsyncSession):
    candidate, offre, application = await _creer_contexte(db)
    # Connaît Python mais pas Django, 1 an sur 3, baccalauréat sur licence.
    analyse = _analyse(candidate.id, application.id, ["python"], 1, "HIGH_SCHOOL")

    score = await scoring_service.compute_and_store_score(
        db, application.id, offre.id, candidate.id, analyse, offre
    )

    assert score.skills_score == 50.0
    assert score.experience_score == pytest.approx(33.33, abs=0.1)
    assert score.education_score == 50.0
    assert score.score_details["missing_skills"] == ["django"]
    assert 0 < score.total_score < 60


@pytest.mark.asyncio
async def test_classement_ordonne_par_score_decroissant(db: AsyncSession):
    """Le rang doit refléter l'ordre des scores, de 1 à N."""
    candidate1, offre, app1 = await _creer_contexte(db)

    # Deux autres candidats sur la MÊME offre.
    autres = []
    for competences, annees, niveau in [
        (["python"], 1, "HIGH_SCHOOL"),          # faible
        (["python", "django"], 10, "PHD"),       # excellent
    ]:
        suffixe = uuid.uuid4().hex[:8]
        user = User(
            email=f"c_{suffixe}@example.com", username=f"c_{suffixe}",
            hashed_password="x", full_name="Autre",
        )
        db.add(user)
        await db.flush()
        cand = Candidate(user_id=user.id, full_name="Autre")
        db.add(cand)
        await db.flush()
        appli = Application(
            candidate_id=cand.id, job_offer_id=offre.id,
            cv_file_path="/tmp/cv.pdf", status="PENDING",
        )
        db.add(appli)
        await db.flush()
        autres.append((cand, appli, competences, annees, niveau))

    # Candidat de référence : profil moyen.
    await scoring_service.compute_and_store_score(
        db, app1.id, offre.id, candidate1.id,
        _analyse(candidate1.id, app1.id, ["python", "django"], 3, "BACHELOR"), offre,
    )
    for cand, appli, competences, annees, niveau in autres:
        await scoring_service.compute_and_store_score(
            db, appli.id, offre.id, cand.id,
            _analyse(cand.id, appli.id, competences, annees, niveau), offre,
        )

    classement = await scoring_service.rank_candidates_for_job(db, offre.id)

    assert len(classement) == 3
    assert [s.rank for s in classement] == [1, 2, 3]
    scores = [s.total_score for s in classement]
    assert scores == sorted(scores, reverse=True), "classement non décroissant"


@pytest.mark.asyncio
async def test_classement_offre_sans_candidat(db: AsyncSession):
    _, offre, _ = await _creer_contexte(db)
    assert await scoring_service.rank_candidates_for_job(db, offre.id) == []


# ══════════════════════════════════════════════════════════════════════════
#  7. CONTRÔLE D'ACCÈS DE L'API
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_classement_exige_une_authentification(client):
    """Les scores sont des données RH sensibles : jamais en accès anonyme."""
    reponse = await client.get(f"/api/v1/recruitment/jobs/{uuid.uuid4()}/ranking")
    assert reponse.status_code in (401, 403)


@pytest.mark.asyncio
async def test_classement_offre_inexistante_renvoie_404(client):
    connexion = await client.post(
        "/api/v1/auth/login",
        json={"email": SUPERADMIN_EMAIL, "password": SUPERADMIN_PASSWORD},
    )
    if connexion.status_code != 200:
        pytest.skip("superadmin non disponible dans cet environnement de test")

    jeton = connexion.json()["access_token"]
    reponse = await client.get(
        f"/api/v1/recruitment/jobs/{uuid.uuid4()}/ranking",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert reponse.status_code == 404
