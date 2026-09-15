"""
Ce que le candidat lit de sa propre candidature.

Ce module existe pour une seule raison : **le moteur de scoring écrit pour le
recruteur**. Ses phrases sont des conseils adressés à un tiers, à propos d'une
personne — « Profil peu compatible. Candidature non recommandée. »,
« Expérience insuffisante ». Montrées à l'intéressé, elles se lisent comme un
refus, alors que le recrutement garde entièrement la décision.

On reconstruit donc un second jeu de formulations à partir des MÊMES données :
des faits, au même niveau que la personne, sans verdict. Le calcul ne change
pas — seule la voix change.

Trois règles tiennent l'ensemble :

1. **On ne recalcule rien.** Le candidat voit exactement ce que voit le RH,
   formulé autrement. Deux chiffres différents détruiraient la confiance que
   cette page cherche à construire.
2. **On annonce les limites.** La correspondance est littérale : « SQL » et
   « PostgreSQL » sont deux mots différents pour la machine. Le taire ferait
   passer l'outil pour incapable de lire.
3. **Ce qui est caché est INVISIBLE**, pas grisé. Une note de test non
   partagée n'apparaît pas — et rien ne signale qu'elle existe.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import Application, Candidate, JobOffer
from app.models.scoring import CandidateScore

logger = logging.getLogger(__name__)

#: Libellés des niveaux d'études, pour ne pas montrer une clé technique.
NIVEAUX = {
    "PHD": "Doctorat", "MASTER": "Master", "INGENIEUR": "Diplôme d'ingénieur",
    "BACHELOR": "Licence", "HIGH_SCHOOL": "Baccalauréat", "NONE": "Non précisé",
}

#: Bandes de lecture. Volontairement larges : la précision du calcul ne
#: justifie pas de distinguer 61 de 64, et un candidat qui lit « 61 » cherche
#: le point manquant au lieu de lire l'essentiel.
BANDES = (
    (75, "forte", "Votre profil correspond largement à ce qui est demandé."),
    (55, "bonne", "Votre profil correspond à l'essentiel de ce qui est demandé."),
    (35, "partielle", "Votre profil correspond en partie à ce qui est demandé."),
    (0,  "faible", "Votre profil s'écarte de ce qui est demandé pour ce poste."),
)


def _niveau(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    return NIVEAUX.get(str(code).upper(), str(code))


class CandidateFeedbackService:
    """Traduit une évaluation interne en une page lisible par son sujet."""

    async def build(self, db: AsyncSession, application_id: UUID,
                    user_id: UUID) -> Optional[dict[str, Any]]:
        """
        Construit le détail destiné au candidat.

        Renvoie `None` si la candidature n'existe pas **ou n'appartient pas**
        au demandeur. Les deux cas se confondent délibérément : distinguer
        « inexistante » de « pas la vôtre » permettrait d'énumérer les
        candidatures des autres.
        """
        ligne = (await db.execute(
            select(Application, JobOffer, CandidateScore)
            .join(Candidate, Application.candidate_id == Candidate.id)
            .join(JobOffer, Application.job_offer_id == JobOffer.id)
            .outerjoin(CandidateScore,
                       CandidateScore.application_id == Application.id)
            .where(Application.id == application_id, Candidate.user_id == user_id)
        )).first()
        if not ligne:
            return None

        application, offre, score = ligne
        detail = (score.score_details or {}) if score else {}

        vue: dict[str, Any] = {
            "application_id": application.id,
            "job_offer_id": offre.id,
            "job_title": offre.title,
            "job_description": offre.description,
            "job_required_skills": list(offre.required_skills or []),
            "job_required_experience_years": offre.required_experience_years,
            "job_required_education_level": _niveau(offre.required_education_level),
            "job_salary_min": offre.salary_min,
            "job_salary_max": offre.salary_max,
            "job_work_mode": offre.work_mode,
            "job_contract_types": list(offre.contract_types or []),
            "applied_at": application.created_at,
            "status": application.status,
            # Le score est analysé en tâche de fond au dépôt : il peut ne pas
            # être encore prêt. L'écran doit pouvoir le dire plutôt que
            # d'afficher un zéro, qui se lirait comme une note catastrophique.
            "analysis_ready": score is not None,
        }

        if score is None:
            return vue

        vue.update(self._correspondance(score, detail))
        vue.update(self._partage_rh(score))
        return vue

    # ── Correspondance ────────────────────────────────────────────────────────

    def _correspondance(self, score: CandidateScore,
                        detail: dict) -> dict[str, Any]:
        total = float(score.total_score or 0)
        bande, phrase = next(
            (b, p) for seuil, b, p in BANDES if total >= seuil
        )

        reconnues = [str(s) for s in (detail.get("matched_skills") or [])]
        absentes = [str(s) for s in (detail.get("missing_skills") or [])]
        demandees = [str(s) for s in (detail.get("required_skills") or [])]

        poids = detail.get("weights") or {}
        annees_detectees = detail.get("extracted_years")
        annees_requises = detail.get("required_years")

        return {
            "score": round(total, 1),
            "band": bande,
            "summary": phrase,
            "weights": {
                "skills": poids.get("skills"),
                "experience": poids.get("experience"),
                "education": poids.get("education"),
            },
            "skills_matched": reconnues,
            "skills_missing": absentes,
            "skills_required": demandees,
            "experience_detected_years": annees_detectees,
            "experience_required_years": annees_requises,
            "education_detected": _niveau(detail.get("extracted_education")),
            "education_required": _niveau(detail.get("required_education")),
            "observations": self._observations(
                score, reconnues, absentes, annees_detectees, annees_requises,
                _niveau(detail.get("extracted_education")),
                _niveau(detail.get("required_education")),
            ),
            "advice": self._conseils(absentes, annees_detectees, annees_requises),
        }

    def _observations(
        self, score: CandidateScore, reconnues: list[str], absentes: list[str],
        annees_detectees, annees_requises,
        formation_detectee: Optional[str], formation_requise: Optional[str],
    ) -> list[dict[str, str]]:
        """
        Ce qui explique le score, énoncé comme un constat.

        Chaque observation dit ce QUI a été lu et ce QUI était demandé. Jamais
        « insuffisant », jamais « peu compatible » : ce sont des jugements que
        le moteur adresse au recruteur, pas des faits à opposer à quelqu'un.
        """
        obs: list[dict[str, str]] = []
        total_demandees = len(reconnues) + len(absentes)

        if total_demandees:
            obs.append({
                "sujet": "Compétences",
                "constat": (
                    f"Sur les {total_demandees} compétences demandées par cette "
                    f"offre, {len(reconnues)} {'a été reconnue' if len(reconnues) == 1 else 'ont été reconnues'} "
                    f"dans votre CV."
                ),
            })

        if annees_requises:
            if annees_detectees is None:
                obs.append({
                    "sujet": "Expérience",
                    "constat": (
                        f"Cette offre demande {annees_requises:g} an(s) "
                        "d'expérience. Nous n'avons pas réussi à relever de "
                        "durée d'expérience dans votre CV — elle y figure "
                        "peut-être sous une forme que notre lecture n'a pas su "
                        "interpréter."
                    ),
                })
            else:
                obs.append({
                    "sujet": "Expérience",
                    "constat": (
                        f"Cette offre demande {annees_requises:g} an(s) "
                        f"d'expérience ; nous en avons relevé "
                        f"{annees_detectees:g} dans votre CV."
                    ),
                })
        elif annees_detectees:
            obs.append({
                "sujet": "Expérience",
                "constat": (f"Nous avons relevé {annees_detectees:g} an(s) "
                            "d'expérience dans votre CV."),
            })

        if formation_requise and formation_requise != "Non précisé":
            obs.append({
                "sujet": "Formation",
                "constat": (
                    f"Cette offre demande le niveau « {formation_requise} » ; "
                    + (f"nous avons relevé « {formation_detectee} » dans votre CV."
                       if formation_detectee
                       else "nous n'avons pas identifié de niveau d'études dans votre CV.")
                ),
            })

        return obs

    def _conseils(self, absentes: list[str], annees_detectees,
                  annees_requises) -> list[str]:
        """
        Quoi en faire.

        Formulés comme « rendez-le visible si vous le pratiquez », jamais
        « ajoutez ces mots ». La nuance n'empêchera pas tout bourrage de
        mots-clés, mais elle évite de l'enseigner — et le test technique fait
        le reste du travail.
        """
        conseils: list[str] = []

        if absentes:
            liste = ", ".join(absentes[:4])
            conseils.append(
                f"Cette offre attend {liste}. Si vous pratiquez l'une de ces "
                "technologies, vérifiez qu'elle apparaît dans votre CV sous le "
                "nom employé par l'offre — nous recherchons les compétences "
                "telles qu'elles y sont nommées."
            )
            conseils.append(
                "Si vous ne les pratiquez pas encore, ce sont les compétences "
                "à travailler pour ce type de poste."
            )

        if annees_requises and annees_detectees is not None \
                and annees_detectees < annees_requises:
            conseils.append(
                "Les durées d'expérience se relèvent mieux lorsque chaque poste "
                "porte ses dates de début et de fin."
            )
        elif annees_requises and annees_detectees is None:
            conseils.append(
                "Indiquer les dates de début et de fin de chaque poste aide à "
                "faire ressortir votre expérience."
            )

        conseils.append(
            "Un score est une correspondance entre un texte et une liste de "
            "critères, pas une évaluation de vos capacités. Chaque candidature "
            "est examinée par un recruteur."
        )
        return conseils

    # ── Ce que le RH a choisi de partager ─────────────────────────────────────

    @staticmethod
    def _partage_rh(score: CandidateScore) -> dict[str, Any]:
        """
        N'ajoute une clé QUE si le RH a ouvert le partage.

        L'absence de clé est le comportement recherché : un champ à `null`
        accompagné d'un libellé apprendrait au candidat qu'il existe une note
        qu'on lui refuse. Ici, il n'y a simplement rien — ni section, ni
        mention, ni trace dans la réponse.
        """
        partage: dict[str, Any] = {}

        if score.test_score_visible and score.test_score is not None:
            partage["test_score"] = round(float(score.test_score), 1)

        if score.interview_feedback_visible and score.candidate_feedback:
            partage["interview_feedback"] = score.candidate_feedback

        return partage


candidate_feedback_service = CandidateFeedbackService()
