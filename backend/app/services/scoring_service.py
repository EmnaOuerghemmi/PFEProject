from uuid import UUID
from datetime import datetime
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from app.models.recruitment import JobOffer, Application
from app.models.scoring import CVAnalysis, CandidateScore

logger = logging.getLogger(__name__)

EDUCATION_LEVELS = {
    "NONE": 0,
    "HIGH_SCHOOL": 1,
    "BACHELOR": 2,
    "INGENIEUR": 3,
    "MASTER": 3,
    "PHD": 4,
}


class ScoringService:
    # Canonical equivalences so the same skill written differently still matches.
    _SKILL_SYNONYMS = {"nodejs": "node", "reactjs": "react", "vuejs": "vue"}

    @staticmethod
    def _normalize_skill_text(text: str) -> str:
        """
        Ramène les noms de frameworks à la forme connue du vocabulaire NLP.

        Couvre les trois écritures rencontrées en pratique : pointée
        (`react.js`), espacée (`react js`) et accolée (`reactjs`). Les formes
        accolées sont indispensables ici car `reactjs` et `vuejs` sont absents
        du vocabulaire : sans cette normalisation, elles ne sont pas
        reconnues, et `_SKILL_SYNONYMS` — appliqué APRÈS l'extraction — ne
        peut pas rattraper un jeton que le vocabulaire n'a jamais produit.
        """
        t = text.lower()
        for a, b in {
            "node.js": "node", "node js": "node", "nodejs": "node",
            "nest.js": "nestjs", "nest js": "nestjs",
            "next.js": "nextjs", "next js": "nextjs",
            "react.js": "react", "react js": "react", "reactjs": "react",
            "vue.js": "vue", "vue js": "vue", "vuejs": "vue",
        }.items():
            t = t.replace(a, b)
        return t

    @staticmethod
    def _canonical_required_skills(required_skills: list[str] | None) -> set[str]:
        """
        Transforme les compétences requises d'une offre en un ensemble de
        jetons canoniques. Re-tokenise via le vocabulaire NLP pour rester
        robuste aux compétences saisies en une seule chaîne séparée par des
        espaces, et aux différentes écritures de frameworks.

        Le repli sur le découpage brut est appliqué **compétence par
        compétence**, et non globalement. Auparavant il ne se déclenchait que
        si le vocabulaire ne reconnaissait ABSOLUMENT RIEN : dès qu'une seule
        compétence était reconnue, toutes les autres — un framework interne,
        un outil métier — étaient silencieusement perdues. L'offre exigeait
        alors moins que prévu et les candidats étaient surnotés.
        """
        if not required_skills:
            return set()
        import re
        from app.services.nlp_service import nlp_service

        canoniques: set[str] = set()
        for brute in required_skills:
            texte = ScoringService._normalize_skill_text(str(brute))
            # Une entrée peut contenir plusieurs compétences séparées par des
            # virgules : on les traite indépendamment pour qu'une inconnue
            # n'entraîne pas la perte de ses voisines.
            for morceau in re.split(r"[,;\n/|]+", texte):
                morceau = morceau.strip()
                if not morceau:
                    continue
                reconnues = {
                    ScoringService._SKILL_SYNONYMS.get(s, s)
                    for s in nlp_service.extract_skills(morceau)
                }
                canoniques |= reconnues if reconnues else {morceau}
        return canoniques

    @staticmethod
    def _canonical_extracted_skills(extracted_skills: list[str] | None) -> set[str]:
        """
        Canonise les compétences extraites du CV.

        Applique la MÊME normalisation que le côté offre : les deux ensembles
        étant comparés par intersection, toute asymétrie produit de faux
        écarts. Un CV mentionnant « React.js » face à une offre exigeant
        « react » comptait auparavant comme une compétence manquante.
        """
        canoniques: set[str] = set()
        for brute in (extracted_skills or []):
            jeton = ScoringService._normalize_skill_text(str(brute)).strip()
            if jeton:
                canoniques.add(ScoringService._SKILL_SYNONYMS.get(jeton, jeton))
        return canoniques

    @staticmethod
    def compute_skills_score(required_skills: list[str] | None, extracted_skills: list[str]) -> float:
        """
        Compute skills match score = matched / required * 100, using canonical
        (normalised, tokenised) skill sets on both sides.
        """
        required_set = ScoringService._canonical_required_skills(required_skills)
        if not required_set:
            return 100.0
        extracted_set = ScoringService._canonical_extracted_skills(extracted_skills)
        matched = len(required_set & extracted_set)
        score = (matched / len(required_set)) * 100.0
        return min(score, 100.0)

    @staticmethod
    def compare_skills(
        required_skills: list[str] | None, extracted_skills: list[str] | None
    ) -> tuple[list[str], list[str]]:
        """
        Sépare les compétences demandées en (retrouvées, manquantes).

        Même canonisation que `compute_skills_score` — c'est le point : un
        écran qui afficherait « React manquant » alors que le score compte
        « react » comme acquis serait incompréhensible.

        Les libellés RENDUS sont ceux de l'offre, pas les jetons canoniques :
        « Spring Boot » se lit mieux que « spring ». La comparaison, elle,
        reste canonique.
        """
        if not required_skills:
            return [], []
        acquises = ScoringService._canonical_extracted_skills(extracted_skills)
        retrouvees: list[str] = []
        manquantes: list[str] = []
        for libelle in required_skills:
            jetons = ScoringService._canonical_required_skills([libelle])
            (retrouvees if jetons & acquises else manquantes).append(str(libelle))
        return retrouvees, manquantes

    @staticmethod
    def compute_experience_score(
        required_years: float | None, extracted_years: float | None
    ) -> float:
        """
        Compute experience match score.
        If no requirement: 100
        If extracted >= required: 100
        If no extracted data: 0
        Otherwise: (extracted / required) * 100
        """
        if required_years is None or required_years == 0:
            return 100.0

        if extracted_years is None:
            return 0.0

        if extracted_years >= required_years:
            return 100.0

        score = (extracted_years / required_years) * 100.0
        return min(score, 100.0)

    @staticmethod
    def compute_education_score(
        required_level: str | None, extracted_level: str
    ) -> float:
        """
        Compute education match score.
        If no requirement: 100
        If extracted >= required: 100
        Otherwise: (extracted_level_value / required_level_value) * 100
        """
        required_key = (required_level or "NONE").upper()
        extracted_key = (extracted_level or "NONE").upper()
        required_value = EDUCATION_LEVELS.get(required_key, 0)
        extracted_value = EDUCATION_LEVELS.get(extracted_key, 0)

        if required_value == 0:
            return 100.0

        if extracted_value >= required_value:
            return 100.0

        score = (extracted_value / required_value) * 100.0
        return min(score, 100.0)

    @staticmethod
    def _generate_report(
        total_score: float,
        skills_score: float,
        experience_score: float,
        education_score: float,
        matched_skills: list[str],
        missing_skills: list[str],
        extracted_years: float | None,
        required_years: float | None,
        extracted_education: str,
        required_education: str | None,
    ) -> tuple[list[str], list[str], str]:
        """Build strengths, weaknesses, and recommendation from computed scores."""
        strengths: list[str] = []
        weaknesses: list[str] = []
        total_required = len(matched_skills) + len(missing_skills)

        # Skills
        if skills_score >= 80:
            strengths.append(
                f"Bonne maîtrise des compétences requises "
                f"({len(matched_skills)} compétence(s) compatible(s))"
            )
        elif skills_score >= 50:
            strengths.append(
                f"Compétences partiellement compatibles "
                f"({len(matched_skills)} sur {total_required})"
            )
        else:
            weaknesses.append(
                f"Peu de compétences requises détectées "
                f"({len(matched_skills)} sur {total_required})"
            )

        if missing_skills:
            weaknesses.append(
                "Compétences manquantes : " + ", ".join(missing_skills[:5])
            )

        # Experience
        if required_years and required_years > 0:
            if experience_score >= 100:
                strengths.append(
                    f"Expérience suffisante ({extracted_years} ans, "
                    f"{required_years} ans requis)"
                )
            elif extracted_years is None:
                weaknesses.append("Expérience non détectable dans le CV")
            else:
                weaknesses.append(
                    f"Expérience insuffisante ({extracted_years} ans, "
                    f"{required_years} ans requis)"
                )
        elif extracted_years and extracted_years > 0:
            strengths.append(f"{extracted_years} ans d'expérience détectés")

        # Education
        if education_score >= 100:
            strengths.append(f"Niveau d'études compatible ({extracted_education})")
        elif required_education and required_education.upper() != "NONE":
            weaknesses.append(
                f"Niveau d'études insuffisant "
                f"(détecté : {extracted_education}, requis : {required_education})"
            )

        # Recommendation
        if total_score >= 80:
            recommendation = (
                "Profil hautement compatible avec le poste. "
                "Candidature fortement recommandée."
            )
        elif total_score >= 60:
            recommendation = "Profil compatible avec le poste. Candidature recommandée."
        elif total_score >= 40:
            recommendation = (
                "Profil partiellement compatible. "
                "Candidature à considérer avec réserves."
            )
        else:
            recommendation = (
                "Profil peu compatible avec le poste. Candidature non recommandée."
            )

        return strengths, weaknesses, recommendation

    @staticmethod
    def compute_total_score(
        skills_score: float,
        experience_score: float,
        education_score: float,
        weight_skills: float = 0.5,
        weight_experience: float = 0.3,
        weight_education: float = 0.2,
    ) -> float:
        """
        Compute total weighted score.
        Normalize weights to sum to 1.0
        """
        total_weight = weight_skills + weight_experience + weight_education
        if total_weight == 0:
            return 0.0

        normalized_ws = weight_skills / total_weight
        normalized_we = weight_experience / total_weight
        normalized_wed = weight_education / total_weight

        total = (
            skills_score * normalized_ws
            + experience_score * normalized_we
            + education_score * normalized_wed
        )
        return min(total, 100.0)

    async def compute_and_store_score(
        self,
        db: AsyncSession,
        application_id: UUID,
        job_offer_id: UUID,
        candidate_id: UUID,
        analysis: CVAnalysis,
        job_offer: JobOffer,
    ) -> CandidateScore:
        """
        Compute scores and store/update CandidateScore record.
        """
        skills_score = self.compute_skills_score(
            job_offer.required_skills, analysis.extracted_skills
        )
        experience_score = self.compute_experience_score(
            job_offer.required_experience_years, analysis.extracted_experience_years
        )
        education_score = self.compute_education_score(
            job_offer.required_education_level, analysis.extracted_education_level or "NONE"
        )

        total_score = self.compute_total_score(
            skills_score,
            experience_score,
            education_score,
            job_offer.weight_skills,
            job_offer.weight_experience,
            job_offer.weight_education,
        )

        required_set = self._canonical_required_skills(job_offer.required_skills)
        extracted_set = self._canonical_extracted_skills(analysis.extracted_skills)
        matched_skills = sorted(required_set & extracted_set)
        missing_skills = sorted(required_set - extracted_set)

        extracted_edu = analysis.extracted_education_level or "NONE"
        strengths, weaknesses, recommendation = self._generate_report(
            total_score, skills_score, experience_score, education_score,
            matched_skills, missing_skills,
            analysis.extracted_experience_years,
            job_offer.required_experience_years,
            extracted_edu,
            job_offer.required_education_level,
        )

        score_details = {
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "required_skills": job_offer.required_skills or [],
            "extracted_years": analysis.extracted_experience_years,
            "required_years": job_offer.required_experience_years,
            "extracted_education": analysis.extracted_education_level,
            "required_education": job_offer.required_education_level,
            "weights": {
                "skills": job_offer.weight_skills,
                "experience": job_offer.weight_experience,
                "education": job_offer.weight_education,
            },
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation": recommendation,
        }

        result = await db.execute(
            select(CandidateScore).where(
                CandidateScore.application_id == application_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.total_score = total_score
            existing.skills_score = skills_score
            existing.experience_score = experience_score
            existing.education_score = education_score
            existing.score_details = score_details
            score = existing
        else:
            score = CandidateScore(
                application_id=application_id,
                job_offer_id=job_offer_id,
                candidate_id=candidate_id,
                total_score=total_score,
                skills_score=skills_score,
                experience_score=experience_score,
                education_score=education_score,
                score_details=score_details,
            )
            db.add(score)

        await db.flush()
        return score

    async def rank_candidates_for_job(
        self, db: AsyncSession, job_offer_id: UUID
    ) -> list[CandidateScore]:
        """
        Rank all candidates for a job by total_score (descending).
        Update rank column for each candidate.
        """
        result = await db.execute(
            select(CandidateScore)
            .where(CandidateScore.job_offer_id == job_offer_id)
            .order_by(CandidateScore.total_score.desc())
        )
        scores = result.scalars().all()

        for rank, score in enumerate(scores, 1):
            score.rank = rank

        return scores

    async def get_analysis_by_application(
        self, db: AsyncSession, application_id: UUID
    ) -> CVAnalysis | None:
        """Fetch CVAnalysis by application ID."""
        result = await db.execute(
            select(CVAnalysis).where(CVAnalysis.application_id == application_id)
        )
        return result.scalar_one_or_none()

    async def get_score_by_application(
        self, db: AsyncSession, application_id: UUID
    ) -> CandidateScore | None:
        """Fetch CandidateScore by application ID."""
        result = await db.execute(
            select(CandidateScore).where(CandidateScore.application_id == application_id)
        )
        return result.scalar_one_or_none()

    async def get_analyses_by_job(
        self, db: AsyncSession, job_offer_id: UUID
    ) -> list[CVAnalysis]:
        """Fetch all CVAnalyses for a job offer."""
        result = await db.execute(
            select(CVAnalysis)
            .join(CandidateScore, CandidateScore.application_id == CVAnalysis.application_id)
            .where(CandidateScore.job_offer_id == job_offer_id)
            .order_by(CandidateScore.total_score.desc())
        )
        return result.scalars().all()

    async def get_scores_by_job(
        self, db: AsyncSession, job_offer_id: UUID
    ) -> list[CandidateScore]:
        """Fetch all CandidateScores for a job offer (ranked)."""
        result = await db.execute(
            select(CandidateScore)
            .where(CandidateScore.job_offer_id == job_offer_id)
            .order_by(CandidateScore.total_score.desc())
        )
        return result.scalars().all()

    async def delete_analysis(
        self, db: AsyncSession, application_id: UUID
    ) -> bool:
        """Delete CVAnalysis by application ID."""
        result = await db.execute(
            select(CVAnalysis).where(CVAnalysis.application_id == application_id)
        )
        analysis = result.scalar_one_or_none()
        if analysis:
            await db.delete(analysis)
            await db.flush()
            return True
        return False

    async def delete_score(
        self, db: AsyncSession, application_id: UUID
    ) -> bool:
        """Delete CandidateScore by application ID."""
        result = await db.execute(
            select(CandidateScore).where(CandidateScore.application_id == application_id)
        )
        score = result.scalar_one_or_none()
        if score:
            await db.delete(score)
            await db.flush()
            return True
        return False


scoring_service = ScoringService()
