"""
Aide à la décision d'embauche — logique pure (aucune base, aucun réseau).

Ce qui est verrouillé ici :

* les seuils sont ceux du classement (85 / 60 / 30), plus les anciens 80/65/50 ;
* « Recruter » exige une évaluation réelle : un excellent CV seul mène à évaluer ;
* un dossier évalué et prêt passe devant un CV excellent mais non vérifié ;
* deux candidats au même score sont départagés, et le critère est expliqué ;
* une réponse suspecte au test pèse avant la réussite aux questions difficiles.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.decision_service import DecisionService
from app.services.hiring_decision_service import SCORE_BANDS, Evidence, rank, recommend


def _ev(nom: str, cv: float, **autres) -> Evidence:
    valeurs = dict(skills_score=70.0, experience_score=60.0, education_score=60.0)
    valeurs.update(autres)
    return Evidence(
        application_id=uuid.uuid4(), candidate_id=uuid.uuid4(),
        candidate_name=nom, cv_score=cv, **valeurs,
    )


def _par_nom(resultats):
    return {r["evidence"].candidate_name: r for r in resultats}


# ── Seuils et recommandation ──────────────────────────────────────────────────

def test_seuils_alignes_sur_le_classement():
    assert SCORE_BANDS == {"excellent": 85.0, "good": 60.0, "average": 30.0}


def test_excellent_cv_sans_evaluation_ne_mene_pas_a_recruter():
    r = recommend(_ev("A", 95))
    assert r["recommendation"] == "INTERVIEW"
    assert "rien n'est encore vérifié" in r["rationale"]


def test_recruter_possible_apres_un_test_rendu():
    r = recommend(_ev("A", 90, test_score=88))
    assert r["recommendation"] == "HIRE"
    assert r["confidence"] == "medium"          # 2 volets sur 3


def test_recruter_confiance_haute_sur_dossier_complet():
    r = recommend(_ev("A", 90, test_score=88, interview_score=86))
    assert r["recommendation"] == "HIRE"
    assert r["confidence"] == "high"


def test_82_est_entretien_et_non_recruter():
    # Ancien bug : 82 donnait « Recruter » ici, « Entretien » au classement.
    assert recommend(_ev("A", 82))["recommendation"] == "INTERVIEW"


def test_score_faible_rejete():
    assert recommend(_ev("A", 20))["recommendation"] == "REJECT"


def test_test_qui_ne_confirme_pas_le_cv_est_signale():
    r = recommend(_ev("A", 80, test_score=25))
    assert any("ne confirme pas le CV" in w for w in r["warnings"])


def test_reponse_suspecte_abaisse_la_confiance():
    sans = recommend(_ev("A", 90, test_score=88, interview_score=86))
    avec = recommend(_ev("A", 90, test_score=88, interview_score=86, anomaly_count=2))
    assert sans["confidence"] == "high" and avec["confidence"] == "medium"
    assert avec["warnings"]


def test_note_manquante_n_est_pas_un_zero():
    # CV 80 + test 60, entretien absent : 69,2 et non 45.
    r = recommend(_ev("A", 80, test_score=60))
    assert r["composite"]["score"] == 69.2
    assert r["composite"]["completeness"] == 2


# ── Classement et départage ───────────────────────────────────────────────────

def test_dossier_evalue_pret_devant_cv_non_verifie():
    res = rank([_ev("CV seul", 92), _ev("Évalué", 88, test_score=90, interview_score=85)])
    assert [r["evidence"].candidate_name for r in res] == ["Évalué", "CV seul"]


def test_ex_aequo_departages_par_le_test_puis_explique():
    res = _par_nom(rank([
        _ev("Fort au test", 70, test_score=70, hard_success_rate=0.75),
        _ev("Faible au test", 70, test_score=70, hard_success_rate=0.25),
    ]))
    gagnant = res["Fort au test"]
    assert gagnant["decision_rank"] == 1
    assert gagnant["tie"]["group_size"] == 2
    assert gagnant["tie"]["decided_by"] == "hard_success_rate"
    assert "75 % contre 25 %" in gagnant["tie"]["explanation"]


def test_reponse_suspecte_compte_avant_les_questions_difficiles():
    res = rank([
        _ev("Suspect", 70, test_score=70, hard_success_rate=1.0, anomaly_count=1),
        _ev("Propre", 70, test_score=70, hard_success_rate=0.5),
    ])
    assert res[0]["evidence"].candidate_name == "Propre"
    assert res[0]["tie"]["decided_by"] == "anomaly_count"


def test_cv_departage_quand_les_evaluations_sont_egales():
    res = rank([
        _ev("Moins de compétences", 70, skills_score=60),
        _ev("Plus de compétences", 70, skills_score=80),
    ])
    assert res[0]["evidence"].candidate_name == "Plus de compétences"
    assert res[0]["tie"]["decided_by"] == "skills_score"


def test_ex_aequo_parfait_renvoye_a_l_entretien():
    res = rank([_ev("A", 70), _ev("B", 70)])
    assert all(r["tie"]["decided_by"] is None for r in res)
    assert "à départager en entretien" in res[0]["tie"]["explanation"]


def test_pas_de_groupe_si_scores_differents():
    res = rank([_ev("A", 75), _ev("B", 65)])
    assert all(r["tie"] is None for r in res)


# ── Évaluation d'offre : unité ────────────────────────────────────────────────

def test_contre_offre_en_tnd_et_non_en_k():
    _, raison, montant = DecisionService().evaluate_offer(2800, 2500, 0.7)
    assert montant is not None
    assert "TND" in raison and "k" not in raison.split("Contre-offre")[-1]


# ── Réponse du modèle : verdict, forces, vigilance, prochaine étape ───────────

def test_entretien_prevu_non_note_bloque_recruter():
    # Cas réel : CV 92, test 83, entretien confirmé mais pas encore noté.
    r = recommend(_ev("A", 92, test_score=83, interview_status="CONFIRMED"))
    assert r["recommendation"] == "INTERVIEW"
    assert "l'entretien est déjà prévu" in r["rationale"]
    assert r["next_step"] == "Saisir la note d'entretien après le rendez-vous prévu."


def test_reponses_suspectes_sans_entretien_bloquent_recruter():
    r = recommend(_ev("A", 92, test_score=90, anomaly_count=1))
    assert r["recommendation"] == "INTERVIEW"
    assert "Planifier un entretien pour vérifier" in r["next_step"]


def test_recruter_jamais_avec_fiabilite_faible():
    cas = [
        _ev("A", 95, test_score=90),
        _ev("B", 95, interview_score=90),
        _ev("C", 95, test_score=90, interview_score=90, anomaly_count=3),
    ]
    for e in cas:
        r = recommend(e)
        if r["recommendation"] == "HIRE":
            assert r["confidence"] != "low"


def test_verdict_chiffre_et_volets_nommes():
    r = recommend(_ev("A", 90, test_score=88, interview_score=86))
    assert "88/100 sur CV, test et entretien" in r["rationale"]


def test_competences_absentes_nommees():
    r = recommend(_ev("A", 70, matched_skills=8, missing_skills=2,
                      missing_skill_names=["Docker", "GitLab"]))
    assert "Compétences requises absentes du CV : Docker, GitLab." in r["warnings"]
    assert "Couvre 8 des 10 compétences requises." in r["strengths"]


def test_test_abandonne_signale_et_relance_proposee():
    r = recommend(_ev("A", 70, test_status="ABANDONNE"))
    assert any("abandonné" in w for w in r["warnings"])
    assert r["next_step"] == "Relancer le candidat ou lui renvoyer un test technique."


def test_points_forts_du_test_cites_avec_chiffres():
    r = recommend(_ev("A", 70, test_score=83, hard_success_rate=1.0, hard_total=3))
    assert "Bon test technique (83/100)." in r["strengths"]
    assert "100 % de réussite aux questions difficiles (3/3)." in r["strengths"]


def test_dossier_pret_renvoie_vers_la_negociation():
    r = recommend(_ev("A", 90, test_score=88, interview_score=86))
    assert r["recommendation"] == "HIRE"
    assert "négociation salariale" in r["next_step"]


# ── Explication rédigée ───────────────────────────────────────────────────────

def test_l_explication_redige_la_mise_en_reserve_et_ses_raisons():
    """Cas réel de la page Décision : CV 75, test 100, entretien 75, mis en réserve."""
    r = recommend(_ev("Candidate Démo", 75, test_score=100, hard_success_rate=1.0, hard_total=3,
                      anomaly_count=3, interview_score=75, matched_skills=9, missing_skills=4,
                      missing_skill_names=["cd", "ci", "cloud", "nosql"]))
    texte = r["explanation"]

    assert r["recommendation"] == "HOLD"
    assert texte.startswith("Je propose de mettre Candidate Démo en réserve et d'attendre "
                            "un candidat plus compétent, car son dossier est correct (84/100 sur "
                            "CV, test et entretien)")
    assert ("En sa faveur : un bon CV (75/100), un test technique excellent (100/100), "
            "100 % de réussite aux questions difficiles (3/3) et un entretien concluant (75/100).") in texte
    assert "En revanche : des compétences requises absentes du CV (cd, ci, cloud, nosql) et " in texte
    assert texte.endswith("Prochaine étape : comparer aux autres candidats de l'offre avant de décider.")
    # Les listes, elles, ne changent pas.
    assert "Bon CV (75/100)." in r["strengths"]
    assert "Compétences requises absentes du CV : cd, ci, cloud, nosql." in r["warnings"]


def test_l_explication_suit_la_recommandation():
    assert recommend(_ev("A", 90, test_score=88, interview_score=86))["explanation"].startswith(
        "Je propose de recruter A, car son dossier est excellent")
    assert recommend(_ev("B", 10, test_score=15))["explanation"].startswith(
        "Je propose de ne pas retenir la candidature de B")
    assert recommend(_ev("C", 75))["explanation"].startswith(
        "Je propose de vérifier le profil de C par le test technique ou un entretien")


def test_sans_point_fort_l_explication_ne_dit_pas_en_revanche():
    texte = recommend(_ev("A", 20, test_score=20))["explanation"]
    assert "En sa faveur" not in texte
    assert "À noter : un CV faible (20/100) et un test technique échoué (20/100)." in texte
