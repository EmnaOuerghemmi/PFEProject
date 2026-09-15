"""
Lot 3 — génération IA du vivier et présélection 30 → 12.

La vérification du lot porte sur deux choses :

1. **Ce que le modèle produit de travers ne doit pas atteindre un candidat.**
   Les questions générées naissent `GENEREE`, et la validation structurelle
   écarte ce qui est inutilisable — bonne réponse hors options, doublons,
   énoncés vides. Ces tests mesurent ce filet sans dépendre d'une clé LLM :
   on soumet à l'agent les réponses que les modèles renvoient réellement.

2. **Les 12 présélectionnées couvrent toutes les compétences de l'offre.**
   Sans cette garantie, un tirage plausible donne douze questions sur une
   seule technologie et le test ne mesure plus le poste.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.question_generator_agent import question_generator_agent as agent
from app.core.security import hash_password
from sqlalchemy import select

from app.models.assessment import QuestionDifficulty, QuestionStatus, TestQuestion
from app.models.recruitment import JobOffer
from app.models.user import User, UserRole
from app.services.assessment_service import assessment_service as svc

from tests.conftest import VALID_PASSWORD


async def _offre(db: AsyncSession, skills=None) -> JobOffer:
    job = JobOffer(
        title="Développeur Full Stack",
        description="Poste Angular / Spring Boot.",
        required_skills=skills if skills is not None else ["Angular", "Java", "SQL"],
        required_experience_years=2, is_active=True, status="PUBLISHED",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


# ── Le parseur face à ce que les modèles renvoient vraiment ───────────────────

def test_le_json_enrobe_dun_bloc_de_code_est_lu():
    """Les modèles enrobent leur JSON malgré la consigne. Il faut le prévoir."""
    brut = """```json
[{"statement":"Que fait git rebase sur une branche ?","options":["A","B","C","D"],
  "answer":"B","explanation":"x","difficulty":"FACILE","skill":"git"}]
```"""
    assert len(agent._parser(brut)) == 1


def test_le_json_precede_dune_phrase_est_lu():
    brut = ('Voici les questions demandées :\n'
            '[{"statement":"Une question assez longue pour passer ?",'
            '"options":["A","B"],"answer":"A"}]')
    assert len(agent._parser(brut)) == 1


def test_une_reponse_sans_json_ne_casse_rien():
    assert agent._parser("Désolé, je ne peux pas répondre.") == []
    assert agent._parser("") == []
    assert agent._parser('{"pas":"un tableau"}') == []


def test_un_json_tronque_ne_casse_rien():
    """Une réponse coupée par la limite de jetons est un cas courant."""
    assert agent._parser('[{"statement":"Question inach') == []


def test_une_reponse_tronquee_rend_ce_quelle_a_de_complet():
    """
    Le défaut le plus coûteux, parce qu'il est silencieux.

    Le modèle s'arrête au milieu d'un énoncé quand il atteint sa limite de
    jetons. `json.loads` échoue alors sur la TOTALITÉ, et vingt-neuf questions
    parfaitement valides partaient à la poubelle avec la trentième — l'écran
    affichait « rien d'exploitable » sans le moindre indice. On récupère les
    objets complets un par un.
    """
    tronque = (
        '[{"statement":"Une première question parfaitement valide ?",'
        '"options":["A","B","C","D"],"answer":"B"},'
        '{"statement":"Une deuxième, complète elle aussi ?",'
        '"options":["A","B"],"answer":"A"},'
        '{"statement":"Une troisième, coupée net au mil'
    )
    lues = agent._parser(tronque)
    assert len(lues) == 2
    assert lues[0]["answer"] == "B"


def test_une_accolade_dans_un_enonce_ne_trompe_pas_la_recuperation():
    """
    Les énoncés techniques en contiennent — `${'{'}variable{'}'}`, `interface{}`.
    Compter les accolades sans tenir compte des chaînes découperait au mauvais
    endroit et perdrait la question.
    """
    tronque = (
        '[{"statement":"Que vaut interface{} en Go, et {ceci} ?",'
        '"options":["A","B"],"answer":"A"},'
        '{"statement":"Coupée ic'
    )
    lues = agent._parser(tronque)
    assert len(lues) == 1
    assert "interface{}" in lues[0]["statement"]


def test_les_lots_restent_sous_la_limite_du_modele():
    """
    La cause racine : trente questions d'un coup dépassent la sortie des
    modèles rapides. Le découpage supprime la classe d'erreur ; ce test empêche
    qu'on revienne à un appel unique.
    """
    from app.agents.question_generator_agent import BANK_TARGET, LOT_PAR_APPEL
    assert LOT_PAR_APPEL < BANK_TARGET
    assert LOT_PAR_APPEL <= 12


# ── La validation structurelle ────────────────────────────────────────────────

@pytest.mark.parametrize("item,attendu", [
    ({"statement": "Que fait git rebase exactement sur une branche ?",
      "options": ["A", "B", "C", "D"], "answer": "Z"},
     "absente des propositions"),
    ({"statement": "court", "options": ["A", "B"], "answer": "A"},
     "trop court"),
    ({"statement": "Une question parfaitement valide et longue ?",
      "options": ["A", "A", "B"], "answer": "A"},
     "en double"),
    ({"statement": "Une question parfaitement valide et longue ?",
      "options": ["A"], "answer": "A"},
     "Moins de deux"),
])
def test_les_defauts_frequents_des_modeles_sont_ecartes(item, attendu):
    """
    Le premier cas est le plus coûteux : une bonne réponse absente des options
    pénalise silencieusement un candidat compétent.
    """
    _, motif = agent._normaliser(item, {"git"}, set())
    assert motif is not None
    assert attendu in motif


def test_un_doublon_denonce_est_ecarte():
    item = {"statement": "Une question parfaitement valide et longue ?",
            "options": ["A", "B", "C", "D"], "answer": "B"}
    vus = {"une question parfaitement valide et longue ?"}
    _, motif = agent._normaliser(item, {"git"}, vus)
    assert motif and "Doublon" in motif


def test_une_question_valide_passe_avec_son_rattachement():
    item = {"statement": "Que fait git rebase sur une branche ?",
            "options": ["A", "B", "C", "D"], "answer": "B",
            "explanation": "Parce que.", "difficulty": "FACILE", "skill": "Git"}
    donnees, motif = agent._normaliser(item, {"git", "java"}, set())
    assert motif is None
    assert donnees["correct_answer"] == ["B"]
    assert donnees["difficulty"] == QuestionDifficulty.FACILE
    assert donnees["skill_tag"] == "git"


def test_un_rattachement_inconnu_nest_pas_invente():
    """Un mauvais tag fausserait le contrôle de couverture du tirage."""
    item = {"statement": "Une question sur un sujet hors périmètre ?",
            "options": ["A", "B", "C", "D"], "answer": "A", "skill": "cobol"}
    donnees, motif = agent._normaliser(item, {"angular", "java"}, set())
    assert motif is None
    assert donnees["skill_tag"] is None


def test_une_difficulte_inconnue_retombe_sur_moyenne():
    item = {"statement": "Une question parfaitement valide et longue ?",
            "options": ["A", "B", "C", "D"], "answer": "A", "difficulty": "IMPOSSIBLE"}
    donnees, _ = agent._normaliser(item, set(), set())
    assert donnees["difficulty"] == QuestionDifficulty.MOYENNE


def test_les_quotas_couvrent_les_trois_difficultes():
    for total in (12, 30, 9):
        quotas = agent._quotas(total)
        assert set(quotas) == set(QuestionDifficulty)
        assert all(n >= 1 for n in quotas.values())


# ── Dégradation sans clé LLM ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sans_cle_llm_la_generation_ne_bloque_rien(db: AsyncSession):
    """
    Le vivier doit rester alimentable à la main : une fonctionnalité qui
    s'effondre faute de clé API n'est pas une fonctionnalité.
    """
    job = await _offre(db)
    if agent.llm_enabled:
        pytest.skip("Une clé LLM est configurée sur cet environnement.")

    rapport = await agent.run(db, job.id, count=30)
    assert rapport["generated"] == 0
    assert "à la main" in " ".join(rapport["reasons"])

    # Et l'ajout manuel fonctionne toujours.
    await svc.create_question(db, job.id, {
        "statement": "Une question écrite à la main ?",
        "options": ["A", "B"], "correct_answer": ["A"],
    })
    await db.commit()
    assert len(await svc.list_questions(db, job.id)) == 1


@pytest.mark.asyncio
async def test_une_offre_inconnue_ne_leve_pas(db: AsyncSession):
    rapport = await agent.run(db, uuid.uuid4())
    assert rapport["generated"] == 0


# ── Présélection 30 → 12 ──────────────────────────────────────────────────────

async def _vivier(db: AsyncSession, job: JobOffer, n: int, skills: list[str]):
    difficultes = [QuestionDifficulty.FACILE, QuestionDifficulty.MOYENNE,
                   QuestionDifficulty.DIFFICILE]
    for i in range(n):
        q = await svc.create_question(db, job.id, {
            "statement": f"Question générée numéro {i} ?",
            "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
            "difficulty": difficultes[i % 3], "skill_tag": skills[i % len(skills)],
        })
        q.status = QuestionStatus.ACTIVE
    await db.commit()


@pytest.mark.asyncio
async def test_les_douze_proposees_couvrent_toutes_les_competences(db: AsyncSession):
    """La vérification du lot : 30 en vivier, 12 proposées, toutes couvertes."""
    job = await _offre(db, skills=["Angular", "Java", "SQL", "Docker"])
    await _vivier(db, job, 30, ["angular", "java", "sql", "docker"])

    retenues = await svc.recommend_questions(db, job.id, count=12)
    rapport = svc.coverage_report(retenues, job.required_skills)

    assert len(retenues) == 12
    assert rapport["competences_manquantes"] == [], rapport
    assert rapport["par_difficulte"] == {"FACILE": 4, "MOYENNE": 5, "DIFFICILE": 3}


@pytest.mark.asyncio
async def test_un_vivier_deficitaire_rend_ce_quil_peut(db: AsyncSession):
    """
    Mieux vaut un test déséquilibré et signalé qu'une liste vide : c'est au RH
    de voir le manque à l'écran et de décider.
    """
    job = await _offre(db, skills=["Angular", "Java"])
    await _vivier(db, job, 5, ["angular"])

    retenues = await svc.recommend_questions(db, job.id, count=12)
    rapport = svc.coverage_report(retenues, job.required_skills)
    assert 0 < len(retenues) <= 5
    assert "java" in rapport["competences_manquantes"]


@pytest.mark.asyncio
async def test_les_questions_non_relues_ne_sont_jamais_proposees(db: AsyncSession):
    """Une question GENEREE ne doit pas franchir la présélection."""
    job = await _offre(db)
    for i in range(10):
        await svc.create_question(db, job.id, {
            "statement": f"Question jamais relue numéro {i} ?",
            "options": ["A", "B"], "correct_answer": ["A"],
        }, generated_by="llm:gemini")
    await db.commit()

    assert await svc.recommend_questions(db, job.id, count=12) == []


@pytest.mark.asyncio
async def test_la_generation_est_reservee_au_rh(client: AsyncClient, db: AsyncSession):
    job = await _offre(db)
    url = f"/api/v1/assessment/jobs/{job.id}/questions/generate"
    assert (await client.post(url)).status_code in (401, 403)


@pytest.mark.asyncio
async def test_le_cycle_de_validation_bout_en_bout(client: AsyncClient, db: AsyncSession):
    """GENEREE → VALIDEE → ACTIVE, et alors seulement tirable."""
    job = await _offre(db)
    suffixe = uuid.uuid4().hex[:6]
    email = f"rh_{suffixe}@example.com"
    db.add(User(
        id=uuid.uuid4(), email=email, username=f"rh_{suffixe}",
        hashed_password=hash_password(VALID_PASSWORD), full_name="RH",
        role=UserRole.ADMIN, is_active=True, is_verified=True,
    ))
    await db.commit()
    token = (await client.post("/api/v1/auth/login",
                               json={"email": email, "password": VALID_PASSWORD})
             ).json()["access_token"]
    entete = {"Authorization": f"Bearer {token}"}

    question = await svc.create_question(db, job.id, {
        "statement": "Une question produite par un modèle ?",
        "options": ["A", "B", "C", "D"], "correct_answer": ["B"],
    }, generated_by="llm:gemini")
    await db.commit()
    assert question.status == QuestionStatus.GENEREE
    assert await svc.recommend_questions(db, job.id) == []

    resp = await client.post(
        f"/api/v1/assessment/questions/{question.id}/status?new_status=VALIDEE",
        headers=entete,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"/api/v1/assessment/jobs/{job.id}/questions/activate", headers=entete
    )
    assert resp.json()["activated"] == 1

    # Pas d'`expire_all()` ici : les objets de cette session ont été modifiés
    # par les requêtes HTTP (qui ont leur propre session). Les expirer force un
    # rechargement paresseux hors contexte greenlet — `MissingGreenlet`. On
    # relit explicitement, ce qui est de toute façon ce qu'on veut vérifier.
    actives = (await db.execute(
        select(TestQuestion).where(
            TestQuestion.job_offer_id == job.id,
            TestQuestion.status == QuestionStatus.ACTIVE,
        )
    )).scalars().all()
    assert len(actives) == 1
