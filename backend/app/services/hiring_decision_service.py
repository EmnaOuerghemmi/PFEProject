"""
Aide à la décision d'embauche : CV, test technique, entretien — et départage.

Ce que le module corrige
------------------------
L'ancienne recommandation ne lisait que le score du CV, avec ses propres
seuils (80/65/50) : un candidat à 82 était « Recruter » ici et « Entretien
recommandé » sur le classement. Pire, elle proposait de recruter quelqu'un
qu'on n'avait ni testé ni rencontré, alors que le classement retire
délibérément la négociation tant qu'aucune évaluation n'a eu lieu.

Trois règles, désormais :

1. **Mêmes seuils que le classement** (`SCORE_BANDS` : 85 / 60 / 30), appliqués
   au score composite — CV, test et entretien — calculé par
   `composite_score_service`, qui ne compte jamais une note manquante pour zéro.
2. **Pas de « Recruter » sans preuve, ni avec un doute ouvert.** Il faut un
   test rendu ou un entretien noté, et aucun doute en suspens (entretien déjà
   prévu mais pas noté, réponses suspectes au test sans entretien pour les
   lever). Chaque réponse est chiffrée : verdict, points forts, points de
   vigilance et une prochaine étape concrète.
3. **Un ex æquo se départage, et le départage s'explique.** Deux candidats au
   même score ne sont pas interchangeables : on compare, dans l'ordre, ce qui a
   été mesuré plutôt que déclaré (test, entretien), la solidité de la mesure
   (questions difficiles, réponses suspectes), puis le détail du CV. Le
   critère décisif est restitué en clair au RH, qui garde la main.

La partie analyse (`recommend`, `rank`) est pure — aucune base, aucun réseau —
pour se tester et se relire isolément. `load_job_evidence` ne fait que lire.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import application_status
from app.models.assessment import AnswerOutcome, QuestionDifficulty, SessionStatus, TestAnswer, TestQuestion, TestSession
from app.models.interview import InterviewInvitation, InvitationStatus
from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore
from app.services.composite_score_service import composite_score_service

logger = logging.getLogger(__name__)

#: Seuils partagés avec la légende du classement (frontend `SCORE_BANDS`).
#: Une seule grille : un même candidat ne peut plus être lu « Recruter » ici
#: et « Entretien recommandé » là-bas.
SCORE_BANDS = {"excellent": 85.0, "good": 60.0, "average": 30.0}

#: En dessous, un test « rendu » ne confirme pas le CV — signalé au RH.
TEST_CONFIRMATION_FLOOR = 40.0

_CONFIANCES = ["low", "medium", "high"]


@dataclass
class Evidence:
    """Tout ce qui est connu d'une candidature au moment de décider."""

    application_id: UUID
    candidate_id: UUID
    candidate_name: str
    cv_score: float
    skills_score: float
    experience_score: float
    education_score: float
    matched_skills: int = 0
    missing_skills: int = 0
    #: Noms des compétences requises absentes du CV — cités au RH plutôt qu'un compte.
    missing_skill_names: list[str] = field(default_factory=list)
    test_status: Optional[str] = None
    test_score: Optional[float] = None
    #: Part de bonnes réponses aux questions DIFFICILES — ce qui sépare le
    #: mieux deux candidats au même score de test.
    hard_success_rate: Optional[float] = None
    hard_total: int = 0
    #: Réponses justes anormalement rapides sur des questions difficiles.
    anomaly_count: int = 0
    overrun_questions: int = 0
    interview_score: Optional[float] = None
    #: Invitation en cours (PENDING / CONFIRMED) — entretien prévu, pas encore noté.
    interview_status: Optional[str] = None
    has_interview_notes: bool = False
    expected_salary: Optional[float] = None
    weights: dict = field(default_factory=dict)
    #: Statut actuel de la candidature, affiché à côté de la recommandation.
    application_status: Optional[str] = None


# ── Analyse ───────────────────────────────────────────────────────────────────

def composite(e: Evidence) -> dict:
    """Score global sur les volets disponibles (voir `composite_score_service`)."""
    return composite_score_service.compute(
        cv_score=e.cv_score,
        test_score=e.test_score,
        interview_score=e.interview_score,
        weights=e.weights or None,
    )


def _abaisser(confiance: str) -> str:
    return _CONFIANCES[max(0, _CONFIANCES.index(confiance) - 1)]


def _volets(c: dict) -> str:
    """« CV et test », « CV, test et entretien »… — sur quoi porte le score."""
    noms = {"cv": "CV", "test": "test", "interview": "entretien"}
    presents = [noms[k] for k in ("cv", "test", "interview") if k in c["available"]]
    if len(presents) == 1:
        return f"{presents[0]} seul"
    return ", ".join(presents[:-1]) + " et " + presents[-1]


def _liste(noms: list[str], maximum: int = 4) -> str:
    texte = ", ".join(noms[:maximum])
    return texte + (f" (+{len(noms) - maximum})" if len(noms) > maximum else "")


@dataclass(frozen=True)
class _Signal:
    """Un même constat sous deux formes : la puce des listes, le fragment du paragraphe."""
    puce: str
    prose: str


def _enumerer(fragments: list[str]) -> str:
    """« a », « a et b », « a, b et c »."""
    if len(fragments) <= 1:
        return "".join(fragments)
    return ", ".join(fragments[:-1]) + " et " + fragments[-1]


def _signaux(e: Evidence) -> tuple[list[_Signal], list[_Signal]]:
    """
    Points forts et points de vigilance, chiffrés et nommés.

    Un RH doit pouvoir vérifier chaque phrase en ouvrant le dossier : « Bon
    test technique (83/100) » se contrôle, « bon profil » ne se contrôle pas.
    """
    forces: list[_Signal] = []
    vigilance: list[_Signal] = []
    bands = SCORE_BANDS

    # ── CV ──
    cv = round(e.cv_score)
    if e.cv_score >= bands["excellent"]:
        forces.append(_Signal(f"CV excellent ({cv}/100).", f"un CV excellent ({cv}/100)"))
    elif e.cv_score >= bands["good"]:
        forces.append(_Signal(f"Bon CV ({cv}/100).", f"un bon CV ({cv}/100)"))
    else:
        niveau = "moyen" if e.cv_score >= bands["average"] else "faible"
        vigilance.append(_Signal(f"CV {niveau} ({cv}/100).", f"un CV {niveau} ({cv}/100)"))

    requis = e.matched_skills + e.missing_skills
    if requis:
        if not e.missing_skills:
            forces.append(_Signal(f"Couvre les {requis} compétences requises par l'offre.",
                                  f"toutes les compétences requises par l'offre ({requis})"))
        else:
            if e.matched_skills / requis >= 0.7:
                forces.append(_Signal(f"Couvre {e.matched_skills} des {requis} compétences requises.",
                                      f"{e.matched_skills} des {requis} compétences requises"))
            absentes = _liste(e.missing_skill_names) if e.missing_skill_names else f"{e.missing_skills}"
            vigilance.append(_Signal(f"Compétences requises absentes du CV : {absentes}.",
                                     f"des compétences requises absentes du CV ({absentes})"))

    # ── Test technique ──
    if e.test_score is not None:
        t = round(e.test_score)
        if e.test_score >= bands["excellent"]:
            forces.append(_Signal(f"Test technique excellent ({t}/100).", f"un test technique excellent ({t}/100)"))
        elif e.test_score >= bands["good"]:
            forces.append(_Signal(f"Bon test technique ({t}/100).", f"un bon test technique ({t}/100)"))
        elif e.test_score >= bands["average"]:
            vigilance.append(_Signal(f"Test technique moyen ({t}/100).", f"un test technique moyen ({t}/100)"))
        else:
            vigilance.append(_Signal(f"Test technique échoué ({t}/100).", f"un test technique échoué ({t}/100)"))

        if e.hard_success_rate is not None and e.hard_total:
            bonnes = round(e.hard_success_rate * e.hard_total)
            pct = round(e.hard_success_rate * 100)
            reussite = f"{pct} % de réussite aux questions difficiles ({bonnes}/{e.hard_total})"
            if e.hard_success_rate >= 0.67:
                forces.append(_Signal(f"{reussite}.", reussite))
            elif e.hard_success_rate <= 0.34:
                vigilance.append(_Signal(f"Seulement {reussite}.", f"seulement {reussite}"))
        if e.overrun_questions:
            hors_delai = f"{e.overrun_questions} question(s) traitée(s) au-delà du temps imparti"
            vigilance.append(_Signal(f"{hors_delai}.", hors_delai))
        if e.anomaly_count:
            rapides = (f"{e.anomaly_count} bonne(s) réponse(s) anormalement rapide(s) à des "
                       "questions difficiles")
            vigilance.append(_Signal(f"{rapides} — à vérifier en entretien.", f"{rapides}, à vérifier en entretien"))
        if e.cv_score >= bands["good"] and e.test_score < TEST_CONFIRMATION_FLOOR:
            vigilance.append(_Signal(f"Le test ({t}/100) ne confirme pas le CV ({cv}/100).",
                                     f"un test ({t}/100) qui ne confirme pas le CV ({cv}/100)"))
    elif e.test_status == "ABANDONNE":
        vigilance.append(_Signal("Test technique abandonné : le lien n'a jamais été ouvert avant son expiration.",
                                 "un test technique abandonné sans avoir été ouvert"))
    elif e.test_status == "ENVOYE":
        vigilance.append(_Signal("Test technique envoyé, pas encore commencé.",
                                 "un test technique envoyé mais pas encore commencé"))
    elif e.test_status == "EN_COURS":
        vigilance.append(_Signal("Test technique en cours.", "un test technique encore en cours"))

    # ── Entretien ──
    if e.interview_score is not None:
        i = round(e.interview_score)
        if e.interview_score >= bands["good"]:
            forces.append(_Signal(f"Entretien concluant ({i}/100).", f"un entretien concluant ({i}/100)"))
        elif e.interview_score >= bands["average"]:
            vigilance.append(_Signal(f"Entretien mitigé ({i}/100).", f"un entretien mitigé ({i}/100)"))
        else:
            vigilance.append(_Signal(f"Entretien défavorable ({i}/100).", f"un entretien défavorable ({i}/100)"))

    return forces, vigilance


def _paragraphe(proposition: str, forces: list[_Signal], vigilance: list[_Signal], etape: str) -> str:
    """
    L'explication rédigée : la proposition et sa raison, ce qui joue pour et
    contre, puis l'action à mener — les mêmes faits que les listes, en prose.
    """
    texte = proposition
    if forces:
        texte += f" En sa faveur : {_enumerer([s.prose for s in forces])}."
    if vigilance:
        lien = "En revanche" if forces else "À noter"
        texte += f" {lien} : {_enumerer([s.prose for s in vigilance])}."
    if etape:
        texte += f" Prochaine étape : {etape[0].lower()}{etape[1:]}"
    return texte


def _prochaine_etape(rec: str, e: Evidence) -> str:
    """Une seule action, la plus utile maintenant — pas une liste de possibles."""
    entretien_prevu = e.interview_score is None and e.interview_status in ("PENDING", "CONFIRMED")
    if rec == "REJECT":
        return "Clôturer la candidature et informer le candidat."
    if rec == "HIRE":
        return "Ouvrir la négociation salariale depuis la page Négociation."
    if entretien_prevu:
        return ("Attendre que le candidat confirme son créneau, puis saisir la note d'entretien."
                if e.interview_status == "PENDING"
                else "Saisir la note d'entretien après le rendez-vous prévu.")
    if e.test_status in ("ENVOYE", "EN_COURS"):
        return "Attendre le résultat du test technique."
    if e.test_score is None and e.test_status == "ABANDONNE":
        return "Relancer le candidat ou lui renvoyer un test technique."
    if e.anomaly_count and e.interview_score is None:
        return "Planifier un entretien pour vérifier les réponses suspectes du test."
    if rec == "HOLD" and e.test_score is None and e.interview_score is None:
        return "Garder en réserve — à évaluer si les profils mieux classés ne conviennent pas."
    if e.test_score is None and e.test_status is None:
        return "Envoyer le test technique, puis planifier un entretien."
    if e.interview_score is None:
        return "Planifier un entretien."
    return "Comparer aux autres candidats de l'offre avant de décider."


def recommend(e: Evidence) -> dict:
    """
    Recommandation d'une candidature : verdict chiffré, points forts, points
    de vigilance et prochaine étape.

    « Recruter » exige une évaluation réelle (test rendu ou entretien noté) ET
    aucun doute ouvert : un entretien déjà prévu mais pas encore noté, ou des
    réponses suspectes au test sans entretien pour les lever, mènent à
    « À confirmer » — jamais à une offre. Un « Recruter » ne peut donc pas
    s'afficher avec une fiabilité faible.
    """
    c = composite(e)
    score = c["score"] or 0.0
    s = round(score)
    volets = _volets(c)
    cv = round(e.cv_score)
    entretien_note = e.interview_score is not None
    evalue = e.test_score is not None or entretien_note
    entretien_prevu = not entretien_note and e.interview_status in ("PENDING", "CONFIRMED")
    forces, vigilance = _signaux(e)
    nom = e.candidate_name

    doutes: list[str] = []
    if e.anomaly_count and not entretien_note:
        doutes.append("des réponses anormalement rapides au test sont à vérifier")
    if entretien_prevu:
        doutes.append("l'entretien est déjà prévu")

    # `verdict` : le constat en une phrase ; `proposition` : la même décision
    # dite au RH, avec sa raison — elle ouvre le paragraphe d'explication.
    if score < SCORE_BANDS["average"]:
        rec, confiance = "REJECT", "high" if evalue else "medium"
        verdict = f"Score global {s}/100 ({volets}) — profil trop éloigné des exigences du poste."
        proposition = (f"Je propose de ne pas retenir la candidature de {nom}, car son score global "
                       f"n'est que de {s}/100 ({volets}), trop loin des exigences du poste.")
    elif not evalue:
        if score >= SCORE_BANDS["good"]:
            rec, confiance = "INTERVIEW", "medium"
            verdict = (
                f"CV excellent ({cv}/100), mais rien n'est encore vérifié : à confirmer "
                "par le test technique ou un entretien avant toute décision."
                if score >= SCORE_BANDS["excellent"]
                else f"Bon CV ({cv}/100), à confirmer par le test technique ou un entretien."
            )
            proposition = (f"Je propose de vérifier le profil de {nom} par le test technique ou un "
                           f"entretien avant de décider, car son CV est "
                           f"{'excellent' if score >= SCORE_BANDS['excellent'] else 'bon'} ({cv}/100) "
                           "mais rien n'est encore vérifié.")
        else:
            rec, confiance = "HOLD", "low"
            verdict = (
                f"CV moyen ({cv}/100) et aucune évaluation — "
                + ("l'entretien prévu permettra de trancher." if entretien_prevu else "à garder en réserve.")
            )
            proposition = (f"Je propose de garder {nom} en réserve, car son CV est moyen ({cv}/100) "
                           "et aucune évaluation n'a encore eu lieu"
                           + (" ; l'entretien prévu permettra de trancher." if entretien_prevu else "."))
    elif score >= SCORE_BANDS["excellent"]:
        if doutes:
            rec, confiance = "INTERVIEW", "medium"
            verdict = (f"Excellent dossier ({s}/100 sur {volets}), à confirmer en entretien avant "
                       f"toute offre : {' ; '.join(doutes)}.")
            proposition = (f"Je propose de confirmer le profil de {nom} en entretien avant toute offre, "
                           f"car son dossier est excellent ({s}/100 sur {volets}) mais "
                           f"{_enumerer(doutes)}.")
        else:
            rec = "HIRE"
            confiance = "high" if c["completeness"] == 3 else "medium"
            verdict = f"Excellent dossier ({s}/100 sur {volets}) — prêt pour la négociation salariale."
            proposition = (f"Je propose de recruter {nom}, car son dossier est excellent "
                           f"({s}/100 sur {volets}) et aucun doute ne reste ouvert.")
    elif score >= SCORE_BANDS["good"]:
        if not entretien_note:
            rec, confiance = "INTERVIEW", "high"
            verdict = (f"Bon dossier ({s}/100 sur {volets}) — "
                       + ("l'entretien prévu permettra de trancher." if entretien_prevu
                          else "un entretien permettra de trancher."))
            proposition = ((f"Je propose d'attendre l'entretien prévu avec {nom} avant de décider"
                            if entretien_prevu else
                            f"Je propose de rencontrer {nom} en entretien avant de décider")
                           + f", car son dossier est bon ({s}/100 sur {volets}) mais pas encore "
                           "confirmé en entretien.")
        else:
            rec, confiance = "HOLD", "medium"
            verdict = (f"Dossier correct après évaluation ({s}/100 sur {volets}) — à comparer "
                       "aux autres candidats de l'offre.")
            proposition = (f"Je propose de mettre {nom} en réserve et d'attendre un candidat plus "
                           f"compétent, car son dossier est correct ({s}/100 sur {volets}) sans "
                           "atteindre le niveau d'un recrutement immédiat.")
    else:
        rec, confiance = "HOLD", "medium"
        verdict = f"Dossier moyen après évaluation ({s}/100 sur {volets}) — à garder en liste d'attente."
        proposition = (f"Je propose de mettre {nom} en réserve et d'attendre un candidat plus "
                       f"compétent, car son dossier reste moyen après évaluation ({s}/100 sur {volets}).")

    # Une réserve n'enlève jamais de points ; elle abaisse la fiabilité.
    if e.anomaly_count:
        confiance = _abaisser(confiance)

    etape = _prochaine_etape(rec, e)
    return {
        "recommendation": rec,
        "confidence": confiance,
        "rationale": verdict,
        "strengths": [f.puce for f in forces],
        "warnings": [v.puce for v in vigilance],
        "next_step": etape,
        "explanation": _paragraphe(proposition, forces, vigilance, etape),
        "composite": c,
    }


@dataclass(frozen=True)
class _Critere:
    cle: str
    libelle: str
    valeur: Callable[[Evidence], Optional[float]]
    format: Callable[[float], str]
    plus_haut_mieux: bool = True


def _pts(v: float) -> str:
    return f"{v:.0f}/100"


def _pct(v: float) -> str:
    return f"{v * 100:.0f} %"


def _nb(v: float) -> str:
    return f"{v:.0f}"


#: Ordre de présentation des recommandations : un dossier évalué et prêt
#: (HIRE) passe devant un excellent CV que rien n'a encore vérifié.
_ORDRE_RECO = {"HIRE": 3, "INTERVIEW": 2, "HOLD": 1, "REJECT": 0}

#: Ordre de départage. Le MESURÉ passe avant le DÉCLARÉ : un test et un
#: entretien disent ce que le candidat sait faire, le CV ce qu'il affirme.
TIE_BREAKERS: list[_Critere] = [
    _Critere("completeness", "nombre de volets évalués",
             lambda e: float(composite(e)["completeness"]), _nb),
    _Critere("test_score", "test technique", lambda e: e.test_score, _pts),
    _Critere("interview_score", "note d'entretien", lambda e: e.interview_score, _pts),
    # Les réponses suspectes AVANT la réussite aux questions difficiles : ces
    # anomalies sont justement des bonnes réponses trop rapides à des
    # questions difficiles — elles gonflent le taux qu'on lirait ensuite.
    _Critere("anomaly_count", "réponses suspectes au test",
             lambda e: float(e.anomaly_count), _nb, plus_haut_mieux=False),
    _Critere("hard_success_rate", "réussite aux questions difficiles",
             lambda e: e.hard_success_rate, _pct),
    _Critere("overrun_questions", "questions hors délai",
             lambda e: float(e.overrun_questions), _nb, plus_haut_mieux=False),
    _Critere("skills_score", "compétences du CV", lambda e: e.skills_score, _pts),
    _Critere("missing_skills", "compétences requises manquantes",
             lambda e: float(e.missing_skills), _nb, plus_haut_mieux=False),
    _Critere("experience_score", "expérience", lambda e: e.experience_score, _pts),
    _Critere("education_score", "formation", lambda e: e.education_score, _pts),
]


def _cle_tri(e: Evidence) -> tuple:
    """
    Clé de départage. Une valeur absente se range DERRIÈRE toute valeur
    présente (un test non passé ne bat pas un test passé), mais n'est pas
    comptée comme un zéro dans la note.
    """
    cle = []
    for c in TIE_BREAKERS:
        v = c.valeur(e)
        if v is None:
            cle.append((0, 0.0))
        else:
            cle.append((1, v if c.plus_haut_mieux else -v))
    return tuple(cle)


def _critere_decisif(a: Evidence, b: Evidence) -> Optional[_Critere]:
    """Premier critère qui place `a` devant `b` — None s'ils sont identiques."""
    for c in TIE_BREAKERS:
        va, vb = c.valeur(a), c.valeur(b)
        if va == vb:
            continue
        return c
    return None


def _explication(gagnant: Evidence, suivant: Evidence) -> str:
    c = _critere_decisif(gagnant, suivant)
    if c is None:
        return (f"Ex æquo parfait avec {suivant.candidate_name} : aucun critère ne les "
                "sépare — à départager en entretien.")
    va, vb = c.valeur(gagnant), c.valeur(suivant)
    if vb is None:
        detail = f"{c.format(va)}, non évalué chez {suivant.candidate_name}"
    else:
        detail = f"{c.format(va)} contre {c.format(vb)}"
    return f"Devant {suivant.candidate_name} au même score grâce à : {c.libelle} ({detail})."


def rank(evidences: list[Evidence]) -> list[dict]:
    """
    Classe les candidatures d'une offre et explique chaque départage.

    Tri : recommandation (HIRE d'abord), score global décroissant, puis
    `TIE_BREAKERS`. Sont « ex æquo » les candidats de même recommandation dont
    le score global ARRONDI est identique — le chiffre que le RH lit à l'écran. Chaque membre d'un groupe reçoit la raison qui le place
    devant le suivant (le dernier, celle qui le place derrière le précédent).
    """
    analyses = [(e, recommend(e)) for e in evidences]
    def _groupe(ar) -> tuple:
        return (_ORDRE_RECO[ar[1]["recommendation"]], round(ar[1]["composite"]["score"] or 0.0))

    analyses.sort(key=lambda ar: (_groupe(ar), _cle_tri(ar[0])), reverse=True)

    resultats: list[dict] = []
    for i, (e, r) in enumerate(analyses):
        resultats.append({"evidence": e, "analysis": r, "decision_rank": i + 1, "tie": None})

    # Groupes d'ex æquo : même recommandation, même score affiché.
    def _cle_groupe(r: dict) -> tuple:
        return (r["analysis"]["recommendation"], round(r["analysis"]["composite"]["score"] or 0.0))

    i = 0
    while i < len(resultats):
        score = round(resultats[i]["analysis"]["composite"]["score"] or 0.0)
        j = i
        while j + 1 < len(resultats) and _cle_groupe(resultats[j + 1]) == _cle_groupe(resultats[i]):
            j += 1
        taille = j - i + 1
        if taille > 1:
            for k in range(i, j + 1):
                courant = resultats[k]["evidence"]
                if k < j:
                    texte = _explication(courant, resultats[k + 1]["evidence"])
                    decisif = _critere_decisif(courant, resultats[k + 1]["evidence"])
                else:
                    precedent = resultats[k - 1]["evidence"]
                    decisif = _critere_decisif(precedent, courant)
                    texte = (
                        f"Derrière {precedent.candidate_name} au même score : "
                        f"{decisif.libelle} moins favorable."
                        if decisif else
                        f"Ex æquo parfait avec {precedent.candidate_name} — à départager en entretien."
                    )
                resultats[k]["tie"] = {
                    "group_size": taille,
                    "score": score,
                    "decided_by": decisif.cle if decisif else None,
                    "explanation": texte,
                }
        i = j + 1
    return resultats


# ── Chargement ────────────────────────────────────────────────────────────────

#: Fins de parcours : plus rien à décider pour ces candidatures.
_EXCLUS = {
    application_status.ApplicationStatus.REJECTED.value,
    application_status.ApplicationStatus.WITHDRAWN.value,
    application_status.ApplicationStatus.HIRED.value,
}


async def load_job_evidence(db: AsyncSession, job_id: UUID) -> list[Evidence]:
    """
    Réunit, pour chaque candidature notée d'une offre, CV, test et entretien.

    Cinq requêtes au total, quel que soit le nombre de candidats — pas une
    par ligne. Les candidatures closes (rejetées, retirées, recrutées) sont
    écartées : il n'y a plus de décision à prendre.
    """
    offre = (await db.execute(select(JobOffer).where(JobOffer.id == job_id))).scalar_one_or_none()
    poids = composite_score_service._weights_for(offre)

    lignes = (await db.execute(
        select(CandidateScore, Application, Candidate)
        .join(Application, CandidateScore.application_id == Application.id)
        .join(Candidate, Application.candidate_id == Candidate.id)
        .where(CandidateScore.job_offer_id == job_id)
    )).all()
    lignes = [l for l in lignes if l[1].status not in _EXCLUS]
    if not lignes:
        return []
    ids = [score.application_id for score, _, _ in lignes]

    # Dernière session de test par candidature (toutes issues confondues pour le
    # statut, la note ne venant que d'une session corrigée).
    sessions = (await db.execute(
        select(TestSession)
        .where(TestSession.application_id.in_(ids))
        .order_by(TestSession.sent_at.desc())
    )).scalars().all()
    derniere: dict[UUID, TestSession] = {}
    for s in sessions:
        derniere.setdefault(s.application_id, s)
    corrigees = {
        app_id: s for app_id, s in derniere.items()
        if s.status in (SessionStatus.TERMINE, SessionStatus.EXPIRE) and s.score is not None
    }

    # Réussite aux questions difficiles des sessions corrigées.
    difficiles: dict[UUID, list[int]] = {}
    if corrigees:
        reponses = (await db.execute(
            select(TestAnswer.session_id, TestAnswer.outcome)
            .join(TestQuestion, TestAnswer.question_id == TestQuestion.id)
            .where(
                TestAnswer.session_id.in_([s.id for s in corrigees.values()]),
                TestQuestion.difficulty == QuestionDifficulty.DIFFICILE,
            )
        )).all()
        for session_id, issue in reponses:
            compte = difficiles.setdefault(session_id, [0, 0])
            compte[1] += 1
            if issue == AnswerOutcome.CORRECTE:
                compte[0] += 1

    invitations = (await db.execute(
        select(InterviewInvitation.application_id, InterviewInvitation.status)
        .where(
            InterviewInvitation.application_id.in_(ids),
            InterviewInvitation.status.in_([InvitationStatus.PENDING, InvitationStatus.CONFIRMED]),
        )
        # Du plus ancien au plus récent : dans le dictionnaire ci-dessous, la
        # dernière ligne l'emporte. Sans tri, l'ordre — donc le résultat — était
        # laissé au hasard dès qu'une candidature avait deux invitations.
        .order_by(InterviewInvitation.created_at)
    )).all()
    entretiens = {app_id: getattr(st, "value", st) for app_id, st in invitations}

    preuves: list[Evidence] = []
    for score, application, candidat in lignes:
        details = score.score_details if isinstance(score.score_details, dict) else {}
        derniere_session = derniere.get(score.application_id)
        session = corrigees.get(score.application_id)
        bonnes, total_dur = difficiles.get(session.id, [0, 0]) if session else (0, 0)
        preuves.append(Evidence(
            application_id=score.application_id,
            candidate_id=score.candidate_id,
            candidate_name=candidat.full_name,
            cv_score=score.total_score,
            skills_score=score.skills_score,
            experience_score=score.experience_score,
            education_score=score.education_score,
            matched_skills=len(details.get("matched_skills") or []),
            missing_skills=len(details.get("missing_skills") or []),
            missing_skill_names=list(details.get("missing_skills") or []),
            test_status=getattr(derniere_session.status, "value", derniere_session.status) if derniere_session else None,
            test_score=session.score if session else None,
            hard_success_rate=(bonnes / total_dur) if total_dur else None,
            hard_total=total_dur,
            anomaly_count=len(session.anomaly_flags or []) if session else 0,
            overrun_questions=session.overrun_question_count if session else 0,
            interview_score=score.interview_score,
            interview_status=entretiens.get(score.application_id),
            has_interview_notes=bool(score.interview_notes),
            expected_salary=application.expected_salary,
            weights=poids,
            application_status=application.status,
        ))
    # Aucune donnée nominative dans les journaux : un compte suffit.
    logger.info("Aide à la décision : %d candidature(s) analysée(s) pour l'offre %s.",
                len(preuves), job_id)
    return preuves
