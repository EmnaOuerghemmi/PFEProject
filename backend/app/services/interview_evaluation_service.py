"""
Évaluation d'entretien : notes du RH, proposition assistée, décision retenue.

Le principe qui gouverne ce module : **la proposition du modèle et la décision
du recruteur sont deux choses distinctes, stockées séparément.**

Les confondre interdirait de savoir plus tard si le RH a suivi la suggestion —
et donc de mesurer si cette suggestion vaut quelque chose. `interview_score`
porte la décision humaine ; `interview_ai_suggestion` conserve la proposition
telle qu'elle a été faite, avec sa date et son modèle.

La proposition est demandée **par critère**, jamais comme un chiffre global.
Une note argumentée critère par critère est vérifiable par le RH ; un nombre
unique sorti de nulle part ne l'est pas — il ne resterait qu'à le croire.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.claude_client import claude_client
from app.integrations.gemini_client import gemini_client
from app.models.recruitment import Application, JobOffer
from app.models.scoring import CandidateScore
from app.utils.helpers import utcnow

logger = logging.getLogger(__name__)

# Grille d'évaluation. Fixe et explicite : deux entretiens notés sur des
# critères différents ne se comparent pas, et un RH ne peut pas contester une
# proposition dont il ignore les axes.
CRITERIA = {
    "communication": "Clarté de l'expression, écoute, structure du propos",
    "technique": "Maîtrise des compétences du poste, profondeur des réponses",
    "adequation": "Adéquation au poste et à l'équipe, compréhension du contexte",
    "motivation": "Intérêt pour le poste, projet professionnel, engagement",
}

_SYSTEM = (
    "Tu assistes un recruteur tunisien qui vient de mener un entretien. À partir "
    "de SES notes, tu proposes une évaluation par critère. Tu ne décides rien : "
    "ta proposition sera relue et modifiée. Réponds UNIQUEMENT par un objet JSON."
)


class InterviewEvaluationService:

    async def get_or_create_score(
        self, db: AsyncSession, application_id: UUID
    ) -> CandidateScore:
        """
        Ligne de score de la candidature.

        Une candidature dont le CV n'a jamais été analysé n'a pas de
        `CandidateScore` : on en crée une à zéro plutôt que d'échouer. Le RH doit
        pouvoir noter un entretien même si l'analyse automatique n'a pas tourné.
        """
        score = (await db.execute(
            select(CandidateScore).where(CandidateScore.application_id == application_id)
        )).scalar_one_or_none()
        if score:
            return score

        application = (await db.execute(
            select(Application).where(Application.id == application_id)
        )).scalar_one_or_none()
        if not application:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidature introuvable.")

        score = CandidateScore(
            application_id=application_id,
            job_offer_id=application.job_offer_id,
            candidate_id=application.candidate_id,
            total_score=0.0, skills_score=0.0,
            experience_score=0.0, education_score=0.0,
        )
        db.add(score)
        await db.flush()
        return score

    async def save_notes(
        self, db: AsyncSession, application_id: UUID, notes: str
    ) -> CandidateScore:
        """Enregistre les notes libres du RH, sans rien noter."""
        score = await self.get_or_create_score(db, application_id)
        score.interview_notes = notes
        await db.flush()
        return score

    async def set_score(
        self, db: AsyncSession, application_id: UUID, valeur: Optional[float],
        *, notes: Optional[str] = None,
    ) -> CandidateScore:
        """
        Fixe la note d'entretien — la DÉCISION, celle qui compte.

        Elle n'écrase jamais `interview_ai_suggestion` : les deux cohabitent,
        précisément pour qu'on puisse plus tard comparer l'une à l'autre.
        """
        if valeur is not None and not (0 <= valeur <= 100):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "La note d'entretien va de 0 à 100.")
        score = await self.get_or_create_score(db, application_id)
        score.interview_score = valeur
        if notes is not None:
            score.interview_notes = notes
        await db.flush()
        return score

    # ── Proposition assistée ──────────────────────────────────────────────────

    @property
    def llm_enabled(self) -> bool:
        return claude_client.available or gemini_client.available

    async def suggest(
        self, db: AsyncSession, application_id: UUID, notes: str
    ) -> dict:
        """
        Propose une évaluation à partir des notes libres du RH.

        Renvoie toujours un dictionnaire exploitable, même sans modèle
        configuré : dans ce cas la proposition est vide et le motif est dit.
        Le RH saisit alors sa note directement — on ne bloque pas un entretien
        sur l'indisponibilité d'une API.

        La proposition est ENREGISTRÉE mais ne devient jamais la note : c'est au
        RH de la reprendre, de la modifier, ou de l'ignorer.
        """
        notes = (notes or "").strip()
        if len(notes) < 20:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Quelques lignes de notes sont nécessaires pour proposer une évaluation.",
            )

        score = await self.get_or_create_score(db, application_id)
        score.interview_notes = notes

        if not self.llm_enabled:
            proposition = {
                "available": False,
                "reason": "Aucun modèle configuré — saisissez la note directement.",
                "criteria": {}, "overall": None, "summary": "",
            }
            await db.flush()
            return proposition

        offre = (await db.execute(
            select(JobOffer)
            .join(Application, Application.job_offer_id == JobOffer.id)
            .where(Application.id == application_id)
        )).scalar_one_or_none()

        brut = self._appeler_modele(self._prompt(offre, notes))
        proposition = self._parser(brut)

        if proposition is None:
            await db.flush()
            return {
                "available": False,
                "reason": "Le modèle n'a rien renvoyé d'exploitable. Saisissez la note directement.",
                "criteria": {}, "overall": None, "summary": "",
            }

        proposition["available"] = True
        proposition["model"] = "claude" if claude_client.available else "gemini"
        proposition["suggested_at"] = utcnow().isoformat()
        # Conservée À PART de la décision : c'est ce qui permettra de mesurer
        # plus tard l'écart entre la suggestion et la note retenue.
        score.interview_ai_suggestion = proposition
        await db.flush()
        logger.info("Évaluation proposée pour la candidature %s (%.0f/100).",
                    application_id, proposition.get("overall") or 0)
        return proposition

    # ── Interne ───────────────────────────────────────────────────────────────

    @staticmethod
    def _prompt(offre: Optional[JobOffer], notes: str) -> str:
        contexte = ""
        if offre:
            competences = ", ".join(offre.required_skills or []) or "non précisées"
            contexte = (f"POSTE : {offre.title}\n"
                        f"COMPÉTENCES ATTENDUES : {competences}\n")
        criteres = "\n".join(f'- "{cle}" : {libelle}' for cle, libelle in CRITERIA.items())

        return f"""{contexte}
NOTES DU RECRUTEUR APRÈS L'ENTRETIEN :
\"\"\"{notes[:3000]}\"\"\"

Propose une évaluation sur ces quatre critères, chacun noté de 0 à 100 :
{criteres}

RÈGLES
1. Note UNIQUEMENT ce que les notes permettent d'étayer. Si un critère n'est
   pas abordé, mets "score": null et explique-le — n'invente pas.
2. Chaque note s'accompagne d'une justification d'une phrase, qui CITE ou
   reformule un élément précis des notes. Une justification générique est
   inutile au recruteur.
3. "overall" est la moyenne des critères effectivement notés.
4. Reste factuel : tu proposes, le recruteur décide.

FORMAT — objet JSON uniquement :
{{"criteria":{{"communication":{{"score":75,"justification":"..."}},
"technique":{{"score":null,"justification":"Non abordé dans les notes."}},
"adequation":{{"score":80,"justification":"..."}},
"motivation":{{"score":70,"justification":"..."}}}},
"overall":75,"summary":"Deux phrases de synthèse."}}"""

    @staticmethod
    def _appeler_modele(prompt: str) -> Optional[str]:
        try:
            if claude_client.available:
                texte = claude_client.complete(prompt=prompt, system=_SYSTEM, max_tokens=1500)
                if texte:
                    return texte
            if gemini_client.available:
                return gemini_client.complete(prompt=prompt, system=_SYSTEM, max_tokens=1500)
        except Exception as exc:  # pragma: no cover - dépend du fournisseur
            logger.warning("Proposition d'évaluation indisponible : %s", exc)
        return None

    @staticmethod
    def _parser(texte: Optional[str]) -> Optional[dict]:
        """
        Extrait la proposition, en recalculant la moyenne plutôt qu'en la
        croyant : les modèles se trompent régulièrement en arithmétique, et une
        moyenne fausse décrédibiliserait toute la suggestion.
        """
        if not texte:
            return None
        texte = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.M).strip()
        debut, fin = texte.find("{"), texte.rfind("}")
        if debut == -1 or fin <= debut:
            return None
        try:
            charge = json.loads(texte[debut:fin + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(charge, dict):
            return None

        criteres: dict[str, dict] = {}
        notes_valides: list[float] = []
        for cle in CRITERIA:
            item = charge.get("criteria", {}).get(cle) or {}
            note = item.get("score")
            try:
                note = None if note is None else max(0.0, min(100.0, float(note)))
            except (TypeError, ValueError):
                note = None
            if note is not None:
                notes_valides.append(note)
            criteres[cle] = {
                "score": note,
                "justification": str(item.get("justification") or "").strip()
                                 or "Non abordé dans les notes.",
            }

        if not notes_valides:
            return None
        return {
            "criteria": criteres,
            "overall": round(sum(notes_valides) / len(notes_valides), 1),
            "summary": str(charge.get("summary") or "").strip(),
        }


interview_evaluation_service = InterviewEvaluationService()
