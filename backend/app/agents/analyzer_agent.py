"""
Analyzer agent — turns raw CV text into structured data.

Wraps the deterministic NLP extractor and adds a short natural-language summary
of the candidate, written by the LOCAL model.

Le texte d'un CV est une donnée personnelle : le résumé n'est demandé qu'au
modèle local (voir app/integrations/llm_router.py), jamais à un service cloud.
Sans modèle local, le résumé déterministe s'applique.

NB : cet agent n'est appelé par aucune route aujourd'hui. Le pipeline réel
d'analyse des CV est `scoring_agent.py`, entièrement déterministe.
"""
from app.agents.base_agent import BaseAgent
from app.integrations import llm_router
from app.services.nlp_service import nlp_service


class AnalyzerAgent(BaseAgent):
    name = "analyzer"

    async def run(self, raw_text: str) -> dict:
        """Extract skills/experience/education/keywords from CV text."""
        extraction = nlp_service.extract_all(raw_text or "")
        extraction["summary"], extraction["summary_model"] = await self._summarize(
            raw_text, extraction
        )
        return extraction

    async def _summarize(self, raw_text: str, extraction: dict) -> tuple[str, str]:
        """(résumé, fournisseur qui l'a produit) — « deterministic » sans modèle."""
        skills = ", ".join(extraction.get("skills", [])[:8]) or "non détectées"
        years = extraction.get("experience_years")
        deterministic = (
            f"Profil avec {years if years is not None else '?'} an(s) d'expérience. "
            f"Compétences clés : {skills}."
        )
        if not raw_text:
            return deterministic, "deterministic"
        reponse = await llm_router.generer(
            f"Résume ce CV en 2 phrases pour un recruteur:\n\n{raw_text[:4000]}",
            donnees_personnelles=True,
            system="Tu es un assistant RH concis et factuel. Réponds en français.",
            max_tokens=200,
        )
        if reponse:
            return reponse.texte, reponse.fournisseur
        return deterministic, "deterministic"


analyzer_agent = AnalyzerAgent()
