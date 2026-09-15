"""
Remplissage assisté du formulaire de création d'offre.

Le RH décrit le poste en langage libre — « Développeur Laravel confirmé, 3 ans
d'expérience, télétravail, CDI, doit connaître PostgreSQL et Docker » — et
l'agent en tire les champs du formulaire : titre, description reformulée,
compétences, expérience, mode de travail, type de contrat.

Deux principes tiennent tout le module, les mêmes que pour le générateur de
questions :

1. **Rien n'est appliqué sans un geste du RH.** L'agent PROPOSE ; il ne
   soumet jamais l'offre lui-même. Un champ mal extrait doit pouvoir être
   corrigé avant tout envoi — comme la suggestion de salaire, qu'on applique
   d'un clic explicite plutôt que de la voir s'imposer.
2. **Aucun champ n'est inventé.** Si le texte ne dit rien du salaire, le champ
   salaire reste vide — jamais une estimation du modèle qui se ferait passer
   pour une donnée du RH. La suggestion de salaire existe déjà, séparément,
   et sait le faire à partir de données de marché réelles ; ce n'est pas le
   rôle de cet agent.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.agents.base_agent import BaseAgent
from app.integrations.gemini_client import gemini_client

logger = logging.getLogger("agent.job_extraction")

#: Vocabulaire fermé que l'agent doit respecter — les mêmes valeurs que les
#: schémas Pydantic de l'offre. Les lui donner évite qu'il invente une
#: variante ("full-remote" au lieu de "REMOTE") que le formulaire rejetterait.
_WORK_MODES = ("ON_SITE", "HYBRID", "REMOTE")
_CONTRACT_TYPES = ("CDI", "CDD", "SIVP", "STAGE", "FREELANCE")
_EDUCATION_LEVELS = ("NONE", "HIGH_SCHOOL", "BACHELOR", "MASTER", "INGENIEUR", "PHD")

#: Une description un peu développée dépasse largement 1200 jetons en
#: français accentué — un texte source riche (compétences multiples, contexte
#: détaillé) a produit une réponse coupée en PLEIN MILIEU de la description,
#: sans accolade fermante. `_parser` renvoyait alors `None` sur un objet
#: pourtant correct aux trois quarts, d'où « la réponse n'a pas pu être
#: interprétée » — sans aucun indice sur la vraie cause. Le filet de
#: récupération ci-dessous absorbe ce qui reste malgré la marge relevée.
_MAX_TOKENS = 2200

_SYSTEM = (
    "Tu aides un recruteur tunisien à remplir une fiche de poste à partir "
    "d'une description en langage libre. Tu n'inventes AUCUNE information "
    "absente du texte : un champ non mentionné reste `null`. Réponds "
    "UNIQUEMENT par un objet JSON, sans texte autour ni bloc de code."
)


def _prompt(texte: str) -> str:
    return f"""Voici la description libre d'un poste, écrite par un recruteur :

\"\"\"{texte.strip()}\"\"\"

Extrait un objet JSON avec EXACTEMENT ces clés :
{{
  "title": "titre du poste, concis, ou null si absent",
  "description": "description reformulée pour une offre publiée — missions, \
contexte, environnement. Développe si le texte source est un simple résumé \
en télégraphique ; reste null seulement si vraiment rien n'est dit du poste",
  "required_skills": ["compétence1", "compétence2"] ou [] si aucune n'est citée,
  "required_experience_years": nombre d'années demandées, ou null,
  "required_education_level": un seul mot parmi {list(_EDUCATION_LEVELS)}, ou null,
  "work_mode": un seul mot parmi {list(_WORK_MODES)}, ou null,
  "contract_types": liste parmi {list(_CONTRACT_TYPES)}, ou [] si non précisé
}}

Ne remplis QUE ce que le texte affirme. Une compétence, une durée ou un mode \
de travail absents du texte doivent rester null ou vides — ne complète jamais \
par une supposition, même plausible."""


class JobExtractionAgent(BaseAgent):
    name = "job_extraction"

    @property
    def llm_enabled(self) -> bool:
        """Claude en premier, Gemini en repli — comme le reste de la plateforme."""
        return self.claude.available or gemini_client.available

    async def run(self, texte: str) -> dict[str, Any]:
        """
        Extrait les champs d'une offre à partir d'une description libre.

        Renvoie toujours un compte rendu, jamais une exception : un échec du
        modèle ne doit pas empêcher le RH de continuer à la main, avec un
        formulaire resté vide plutôt que bloqué.
        """
        texte = (texte or "").strip()
        if len(texte) < 15:
            return {"ok": False, "fields": {},
                    "reason": "Décrivez le poste en quelques phrases avant de générer."}

        if not self.llm_enabled:
            return {"ok": False, "fields": {},
                    "reason": "Aucun modèle configuré. Remplissez le formulaire à la main."}

        brut = self._appeler_modele(_prompt(texte))
        if not brut:
            return {"ok": False, "fields": {},
                    "reason": "Le modèle n'a rien renvoyé d'exploitable."}

        objet = self._parser(brut)
        if not objet:
            return {"ok": False, "fields": {},
                    "reason": "La réponse du modèle n'a pas pu être interprétée."}

        return {"ok": True, "fields": self._nettoyer(objet), "reason": None}

    # ── Interne ───────────────────────────────────────────────────────────────

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
    def _parser(texte: str) -> Optional[dict]:
        """
        Isole l'objet JSON de la réponse, même enrobé d'un bloc de code ou
        d'une phrase d'introduction — les modèles le font malgré la consigne.
        """
        texte = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.M).strip()
        debut = texte.find("{")
        if debut == -1:
            return None

        fin = texte.rfind("}")
        if fin > debut:
            try:
                objet = json.loads(texte[debut:fin + 1])
                if isinstance(objet, dict):
                    return objet
            except json.JSONDecodeError:
                pass                      # objet présent mais mal formé : on récupère

        # Réponse TRONQUÉE — le budget de jetons a manqué en plein milieu d'un
        # champ (typiquement la description, la plus longue). Perdre TOUT
        # l'objet pour un seul champ coupé serait dommage : on récupère les
        # paires clé/valeur COMPLÈTES qui précèdent la coupure.
        return JobExtractionAgent._reparer_objet_tronque(texte[debut:])

    @staticmethod
    def _reparer_objet_tronque(fragment: str) -> Optional[dict]:
        """
        Reconstruit ce qui est récupérable d'un objet coupé en cours de
        génération.

        On avance caractère par caractère en suivant la profondeur des
        crochets/accolades — en ignorant ce qui est DANS une chaîne, sinon une
        accolade au milieu d'un texte de description compterait à tort. Le
        dernier point où l'objet était dans un état valide (juste après une
        virgule séparant deux paires clé/valeur au premier niveau) sert de
        point de coupe : tout ce qui suit — le champ en cours d'écriture au
        moment de la troncature — est abandonné.
        """
        profondeur = 0
        dans_chaine = echappe = False
        dernier_point_sur = None       # position juste après la dernière virgule sûre

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
            if c in "{[":
                profondeur += 1
            elif c in "}]":
                profondeur -= 1
            elif c == "," and profondeur == 1:
                dernier_point_sur = i + 1

        if dernier_point_sur is None:
            return None
        try:
            objet = json.loads(fragment[:dernier_point_sur].rstrip().rstrip(",") + "}")
        except json.JSONDecodeError:
            return None
        return objet if isinstance(objet, dict) else None

    @staticmethod
    def _nettoyer(objet: dict) -> dict[str, Any]:
        """
        Ne renvoie que des champs valides pour le formulaire.

        Une valeur hors vocabulaire (un mode de travail halluciné, par
        exemple) est écartée plutôt que transmise telle quelle : le
        formulaire la rejetterait de toute façon, avec un message moins clair
        pour le RH que « ce champ est resté vide ».
        """
        champs: dict[str, Any] = {}

        titre = objet.get("title")
        if isinstance(titre, str) and titre.strip():
            champs["title"] = titre.strip()[:200]

        description = objet.get("description")
        if isinstance(description, str) and description.strip():
            champs["description"] = description.strip()

        competences = objet.get("required_skills")
        if isinstance(competences, list):
            propres = [str(c).strip() for c in competences if str(c).strip()]
            if propres:
                champs["required_skills"] = propres[:20]

        annees = objet.get("required_experience_years")
        if isinstance(annees, (int, float)) and 0 <= annees <= 50:
            champs["required_experience_years"] = float(annees)

        formation = objet.get("required_education_level")
        if isinstance(formation, str) and formation.upper() in _EDUCATION_LEVELS:
            champs["required_education_level"] = formation.upper()

        mode = objet.get("work_mode")
        if isinstance(mode, str) and mode.upper() in _WORK_MODES:
            champs["work_mode"] = mode.upper()

        contrats = objet.get("contract_types")
        if isinstance(contrats, list):
            propres = [str(c).upper() for c in contrats if str(c).upper() in _CONTRACT_TYPES]
            if propres:
                champs["contract_types"] = sorted(set(propres), key=propres.index)

        return champs


job_extraction_agent = JobExtractionAgent()
