"""
Génération du vivier de questions techniques d'une offre.

L'agent produit une trentaine de questions à partir des compétences requises,
du niveau d'expérience attendu et de la description du poste. Il ne les met
JAMAIS en service : elles naissent `GENEREE` et attendent qu'un RH les relise.

C'est la seule barrière entre une fausse bonne réponse et un candidat pénalisé
sans que personne ne le sache. Un modèle qui écrit trente questions techniques
en produira quelques-unes dont la bonne réponse est fausse, ambiguë, ou dont
deux options sont correctes — et rien dans la note finale ne le signalera.

Deux filets avant même la relecture humaine :

* le **prompt** exige des distracteurs bâtis sur des erreurs plausibles, une
  explication par question et un rattachement à une compétence de l'offre ;
* la **validation structurelle** rejette en silence ce qui est inutilisable —
  bonne réponse absente des options, QCM à une seule proposition, doublons.
  Mieux vaut rendre 24 questions saines que 30 dont 6 sont à jeter.

Sans clé LLM configurée, l'agent ne génère rien et le dit : le vivier reste
alimentable à la main, la fonctionnalité n'est pas bloquée.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.integrations.gemini_client import gemini_client
from app.models.assessment import (
    DIFFICULTY_TEMPLATE, QuestionDifficulty, QuestionKind, TestQuestion,
)
from app.models.recruitment import JobOffer
from app.services.assessment_service import assessment_service

# Taille du vivier visée. Trois fois le test : de quoi tirer des sujets
# différents d'un candidat à l'autre sans jamais sortir du même ensemble.
BANK_TARGET = 30

#: Questions demandées par appel. Trente d'un coup dépassent la limite de sortie
#: des modèles rapides : la réponse est coupée en plein milieu d'un énoncé, et
#: tout le lot est perdu. Découper coûte quelques secondes et supprime la classe
#: d'erreur entière.
LOT_PAR_APPEL = 10

#: Marge confortable pour un lot. Un objet question pèse ~350 jetons.
_MAX_TOKENS = 8000

_SYSTEM = (
    "Tu rédiges des questions d'évaluation technique pour un recrutement en "
    "Tunisie. Tu réponds UNIQUEMENT par un tableau JSON valide, sans texte "
    "autour, sans bloc de code."
)


def _prompt(offre: JobOffer, quotas: dict[QuestionDifficulty, int]) -> str:
    competences = ", ".join(offre.required_skills or []) or "développement logiciel"
    experience = offre.required_experience_years
    niveau = (
        "débutant (0-2 ans)" if experience is None or experience < 2
        else "confirmé (2-5 ans)" if experience < 5
        else "senior (5 ans et plus)"
    )
    repartition = " · ".join(f"{n} {d.value}" for d, n in quotas.items())

    return f"""Rédige {sum(quotas.values())} questions à choix multiple pour évaluer un candidat au poste suivant.

POSTE : {offre.title}
NIVEAU ATTENDU : {niveau}
COMPÉTENCES À COUVRIR : {competences}
DESCRIPTION : {(offre.description or '')[:800]}

RÉPARTITION EXIGÉE : {repartition}

RÈGLES IMPÉRATIVES
1. Chaque question porte sur UNE compétence de la liste, indiquée dans "skill".
   Répartis les questions sur TOUTES les compétences, pas seulement la première.
2. Exactement 4 propositions par question, dont UNE SEULE correcte.
3. Les 3 propositions fausses sont des ERREURS PLAUSIBLES — ce qu'un candidat
   qui a mal compris répondrait réellement. Jamais d'option absurde ni de
   remplissage : une option évidemment fausse ne teste rien.
4. "answer" reprend MOT POUR MOT l'une des propositions.
5. "explanation" dit en une phrase pourquoi la réponse est correcte. Elle sert
   au recruteur qui relit, pas au candidat.
6. Teste la compréhension et le raisonnement, pas la mémorisation de syntaxe.
7. Pas de question dont la réponse dépend d'une version précise d'un outil.

FORMAT — tableau JSON, un objet par question :
[{{"statement":"...","options":["...","...","...","..."],"answer":"...","explanation":"...","difficulty":"FACILE|MOYENNE|DIFFICILE","skill":"..."}}]"""


class QuestionGeneratorAgent(BaseAgent):
    name = "question_generator"

    @property
    def llm_enabled(self) -> bool:
        """Claude en premier, Gemini en repli — comme le reste de la plateforme."""
        return self.claude.available or gemini_client.available

    async def run(self, db: AsyncSession, job_offer_id: UUID, *,
                  count: int = BANK_TARGET) -> dict[str, Any]:
        """
        Génère le vivier d'une offre et l'enregistre en statut GENEREE.

        Retourne un compte rendu plutôt qu'une simple liste : le nombre de
        questions écartées et la raison de chaque rejet sont ce qui permet de
        juger si le prompt tient. Sans cette mesure, on ne saurait pas si le
        modèle produit du solide.
        """
        offre = (await db.execute(
            select(JobOffer).where(JobOffer.id == job_offer_id)
        )).scalar_one_or_none()
        if not offre:
            return {"generated": 0, "rejected": 0, "reasons": ["Offre introuvable."]}

        if not self.llm_enabled:
            self.logger.info("Aucune clé LLM configurée — génération ignorée.")
            return {
                "generated": 0, "rejected": 0,
                "reasons": ["Aucun modèle configuré. Le vivier reste alimentable à la main."],
            }

        # Découpage en lots. Demander trente questions d'un coup dépassait la
        # limite de sortie du modèle : la réponse arrivait coupée en plein
        # milieu d'un énoncé, et le lot entier était perdu sans qu'on sache
        # pourquoi. Plusieurs appels courts suppriment la cause ; la
        # récupération du parseur reste le filet.
        candidates: list[dict] = []
        echecs = 0
        restant = count
        while restant > 0:
            lot = min(LOT_PAR_APPEL, restant)
            brut = self._appeler_modele(_prompt(offre, self._quotas(lot)))
            if not brut:
                echecs += 1
                if echecs >= 2:           # le modèle ne répond pas : on arrête
                    break
            else:
                obtenues = self._parser(brut)
                if not obtenues:
                    echecs += 1
                candidates.extend(obtenues)
            restant -= lot

        if not candidates:
            return {"generated": 0, "rejected": 0,
                    "reasons": ["Le modèle n'a rien renvoyé d'exploitable. "
                                "Vérifiez le nom du modèle configuré "
                                "(GEMINI_MODEL) : les anciennes versions sont "
                                "retirées sans préavis et répondent 404."]}

        competences = {str(s).strip().lower() for s in (offre.required_skills or [])}

        enregistrees, rejets = 0, []
        vus_enonces: set[str] = set()
        for item in candidates:
            donnees, motif = self._normaliser(item, competences, vus_enonces)
            if motif:
                rejets.append(motif)
                continue
            try:
                await assessment_service.create_question(
                    db, job_offer_id, donnees, generated_by=self._source(),
                )
                vus_enonces.add(donnees["statement"].strip().lower())
                enregistrees += 1
            except Exception as exc:
                # La validation structurelle du service a parlé : on note et on
                # continue. Une question fautive ne doit pas faire échouer les 29
                # autres.
                rejets.append(str(getattr(exc, "detail", exc))[:120])

        await db.flush()
        self.logger.info(
            "Vivier de l'offre %s : %d question(s) générée(s), %d écartée(s).",
            job_offer_id, enregistrees, len(rejets),
        )
        return {"generated": enregistrees, "rejected": len(rejets), "reasons": rejets[:10]}

    # ── Interne ───────────────────────────────────────────────────────────────

    def _source(self) -> str:
        return "llm:claude" if self.claude.available else "llm:gemini"

    def _appeler_modele(self, prompt: str) -> Optional[str]:
        """Claude d'abord, Gemini ensuite. Jamais d'exception remontée."""
        try:
            if self.claude.available:
                texte = self.claude.complete(prompt=prompt, system=_SYSTEM, max_tokens=_MAX_TOKENS)
                if texte:
                    return texte
            if gemini_client.available:
                return gemini_client.complete(prompt=prompt, system=_SYSTEM, max_tokens=_MAX_TOKENS)
        except Exception as exc:  # pragma: no cover - dépend du fournisseur
            self.logger.warning("Appel au modèle échoué : %s", exc)
        return None

    @staticmethod
    def _parser(texte: str) -> list[dict]:
        """
        Extrait le tableau JSON de la réponse.

        Les modèles enrobent volontiers leur JSON d'un bloc de code ou d'une
        phrase d'introduction, malgré la consigne. On isole donc le premier
        tableau plutôt que d'exiger une réponse parfaitement propre.
        """
        texte = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.M).strip()
        debut = texte.find("[")
        if debut == -1:
            return []

        fin = texte.rfind("]")
        if fin > debut:
            try:
                charge = json.loads(texte[debut:fin + 1])
                if isinstance(charge, list):
                    return [x for x in charge if isinstance(x, dict)]
            except json.JSONDecodeError:
                pass                      # tableau présent mais mal formé : on récupère

        # Réponse TRONQUÉE — le cas le plus coûteux, parce qu'il est silencieux.
        # Le modèle s'arrête au milieu d'une chaîne quand il atteint sa limite
        # de jetons ; `json.loads` échoue alors sur la totalité, et vingt-neuf
        # questions parfaitement valides partent à la poubelle avec la
        # trentième. On récupère donc les objets COMPLETS un par un.
        return QuestionGeneratorAgent._objets_complets(texte[debut + 1:])

    @staticmethod
    def _objets_complets(fragment: str) -> list[dict]:
        """
        Isole les objets JSON entiers d'un fragment, en ignorant le dernier s'il
        est coupé.

        On suit la profondeur des accolades en tenant compte des chaînes et des
        échappements : une accolade DANS un énoncé ne doit pas compter.
        """
        objets: list[dict] = []
        profondeur = depart = 0
        dans_chaine = echappe = False

        for i, c in enumerate(fragment):
            if echappe:
                echappe = False
                continue
            if c == "\\":
                echappe = True
                continue
            if c == '"':
                dans_chaine = not dans_chaine
                continue
            if dans_chaine:
                continue
            if c == "{":
                if profondeur == 0:
                    depart = i
                profondeur += 1
            elif c == "}":
                profondeur -= 1
                if profondeur == 0:
                    try:
                        valeur = json.loads(fragment[depart:i + 1])
                        if isinstance(valeur, dict):
                            objets.append(valeur)
                    except json.JSONDecodeError:
                        pass
                elif profondeur < 0:
                    break
        return objets

    @staticmethod
    def _normaliser(item: dict, competences: set[str],
                    vus: set[str]) -> tuple[dict, Optional[str]]:
        """
        Met une question du modèle au format du vivier, ou dit pourquoi elle est
        inutilisable. Les contrôles ici sont ceux qu'un modèle rate le plus.
        """
        enonce = str(item.get("statement") or "").strip()
        if len(enonce) < 10:
            return {}, "Énoncé vide ou trop court."
        if enonce.lower() in vus:
            return {}, f"Doublon : « {enonce[:50]}… »"

        options = [str(o).strip() for o in (item.get("options") or []) if str(o).strip()]
        if len(options) < 2:
            return {}, f"Moins de deux propositions : « {enonce[:50]}… »"
        if len(set(options)) != len(options):
            return {}, f"Propositions en double : « {enonce[:50]}… »"

        reponse = str(item.get("answer") or "").strip()
        if reponse not in options:
            # L'erreur la plus fréquente, et la plus coûteuse : la bonne réponse
            # ne figure pas parmi les propositions. Un candidat compétent la
            # raterait forcément.
            return {}, f"Bonne réponse absente des propositions : « {enonce[:50]}… »"

        try:
            difficulte = QuestionDifficulty(str(item.get("difficulty", "MOYENNE")).upper())
        except ValueError:
            difficulte = QuestionDifficulty.MOYENNE

        skill = str(item.get("skill") or "").strip().lower() or None
        if skill and competences and skill not in competences:
            # On garde la question mais on ne lui invente pas un rattachement :
            # un mauvais tag fausserait le contrôle de couverture du tirage.
            skill = next((c for c in competences if c in skill or skill in c), None)

        return {
            "statement": enonce,
            "options": options,
            "correct_answer": [reponse],
            "explanation": str(item.get("explanation") or "").strip() or None,
            "difficulty": difficulte,
            "kind": QuestionKind.QCM_UNIQUE,
            "skill_tag": skill,
        }, None

    @staticmethod
    def _quotas(count: int) -> dict[QuestionDifficulty, int]:
        """Répartit la commande sur les trois difficultés, au prorata du gabarit."""
        total_gabarit = sum(DIFFICULTY_TEMPLATE.values())
        quotas, attribues = {}, 0
        difficultes = list(DIFFICULTY_TEMPLATE)
        for difficulte in difficultes[:-1]:
            part = max(1, round(count * DIFFICULTY_TEMPLATE[difficulte] / total_gabarit))
            quotas[difficulte] = part
            attribues += part
        quotas[difficultes[-1]] = max(1, count - attribues)
        return quotas


question_generator_agent = QuestionGeneratorAgent()
