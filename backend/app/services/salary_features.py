"""
Construction des features salariales — **contrat partagé** entre l'entraînement
(`scripts/salary_ml_pipeline.py`) et l'inférence (`salary_prediction_service`).

Ces deux chemins doivent produire des vecteurs identiques pour une même entrée.
Le moindre écart — un mot-clé détecté d'un côté et pas de l'autre, un titre
normalisé différemment — produit une prédiction fausse sans lever d'erreur. Ils
importent donc tous les deux ce module au lieu de réimplémenter la logique.

Trois défauts corrigés ici, tous constatés en production :

1. **`java` détecté dans « JavaScript ».** La correspondance des compétences se
   faisait par sous-chaîne : une offre React/Node se voyait attribuer Java, un
   profil mieux payé. La détection se fait désormais sur des limites de mots.

2. **Titres français jamais reconnus.** Le barème est en anglais
   (`full stack developer`), les offres en français
   (« Développeur(se) Full Stack Junior – Node.js / React.js »). La recherche
   échouait systématiquement et retombait sur la bande générique de la
   catégorie. Les titres sont maintenant normalisés puis rapprochés du barème
   par recouvrement de tokens.

3. **Le niveau d'études a été retiré des features.** Dans le dataset, il est
   entièrement déterminé par la séniorité (tous les Junior sont « Licence »,
   tous les Lead « Master ») : le modèle l'avait appris comme un proxy de
   séniorité. Renseigner « Ingénieur » sur une offre junior faisait donc croire
   au modèle à un profil confirmé et gonflait la prédiction de plus de 50 %.
   Une variable colinéaire qui n'apporte rien mais peut tout casser n'a pas sa
   place dans le vecteur.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# Mots de séniorité et mentions de genre à retirer d'un intitulé avant
# rapprochement : ils décrivent le niveau ou la forme, pas le métier.
_TITLE_NOISE = {
    "junior", "jr", "senior", "sr", "lead", "principal", "confirme", "confirmé",
    "debutant", "débutant", "stagiaire", "stage", "intern", "alternant",
    "h", "f", "hf", "e", "se", "x", "the", "de", "du", "des", "en", "et", "a",
}

# Traduction des termes métier fréquents. Le barème étant en anglais, un
# intitulé français doit être ramené à son équivalent pour être rapproché.
_FR_EN = {
    "developpeur": "developer", "developpeuse": "developer", "developpement": "development",
    "ingenieur": "engineer", "ingenieure": "engineer",
    "concepteur": "developer", "programmeur": "developer",
    "analyste": "analyst", "architecte": "architect",
    "chef": "manager", "responsable": "manager", "directeur": "director",
    "charge": "specialist", "chargee": "specialist",
    "recruteur": "recruiter", "recrutement": "recruiter",
    "comptable": "accountant", "commercial": "sales", "vendeur": "sales",
    "designer": "designer", "graphiste": "graphic designer",
    "testeur": "qa", "qualite": "qa",
    "reseau": "network", "reseaux": "network", "securite": "cybersecurity",
    "mobile": "mobile", "embarque": "embedded", "logiciel": "software",
    "donnees": "data", "projet": "project", "produit": "product",
    "marketing": "marketing", "financier": "financial", "finance": "finance",
    "support": "support", "administrateur": "admin", "assistant": "assistant",
    "fullstack": "full stack", "front": "frontend", "back": "backend",
}

# Seuil de recouvrement au-delà duquel deux intitulés sont considérés comme le
# même métier. 0.5 = la moitié des mots significatifs en commun.
_TITLE_MATCH_THRESHOLD = 0.5


def strip_accents(text: str) -> str:
    """« Développeur » -> « developpeur ». Les intitulés saisis varient en accents."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def normalize_text(text: str) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces."""
    cleaned = strip_accents(str(text or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#. ]+", " ", cleaned)).strip()


def skill_hits(skills_text: str, vocab: Iterable[str]) -> list[int]:
    """
    Multi-hot des compétences, sur des LIMITES DE MOTS.

    `"java" in "javascript"` est vrai en Python : la détection par sous-chaîne
    attribuait Java à toute offre mentionnant JavaScript. On exige donc que le
    terme soit délimité — `node.js` reste détecté par `node`, mais `javascript`
    ne déclenche plus `java`.
    """
    haystack = normalize_text(skills_text)
    bits = []
    for term in vocab:
        needle = normalize_text(term)
        if not needle:
            bits.append(0)
            continue
        # \b ne fonctionne pas après un '+' ou un '#' (c#, c++) : on encadre par
        # un début/fin de chaîne ou un caractère non alphanumérique.
        motif = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        bits.append(1 if re.search(motif, haystack) else 0)
    return bits


# Marques de genre / format accolées à l'intitulé : « (se) », « (e) », « (H/F) ».
# Elles doivent disparaître AVANT tout découpage, sinon la parenthèse tronque le
# titre — « Développeur(se) Full Stack » se réduisait à « Développeur », qui
# recouvre autant « .net developer » que « full stack developer ».
_GENDER_MARK = re.compile(r"\(\s*(?:se|e|s|h\s*/?\s*f|f\s*/?\s*h|m\s*/?\s*f)\s*\)", re.I)


def _title_tokens(title: str) -> set[str]:
    """Mots significatifs d'un intitulé : traduits, sans bruit ni séniorité."""
    sans_genre = _GENDER_MARK.sub("", str(title or ""))
    # On coupe ensuite sur les séparateurs qui introduisent la stack technique :
    # « Développeur Full Stack Junior – Node.js / React.js » -> partie utile.
    principal = re.split(r"[–—|:(]|\s-\s", sans_genre, maxsplit=1)[0]
    if len(normalize_text(principal)) < 4:      # séparateur trop précoce
        principal = sans_genre
    mots = normalize_text(principal).split()
    tokens = set()
    for mot in mots:
        mot = _FR_EN.get(mot, mot)
        for part in mot.split():                # « graphic designer » -> 2 tokens
            if part and part not in _TITLE_NOISE and len(part) > 1:
                tokens.add(part)
    return tokens


def canonical_title(title: str, known_titles: Iterable[str]) -> Optional[str]:
    """
    Rapproche un intitulé libre du titre du barème qui lui correspond.

    Renvoie la clé exacte du barème, ou `None` si aucun titre connu ne recouvre
    suffisamment l'intitulé — auquel cas l'appelant retombe sur la bande de la
    catégorie, ce qui reste correct mais moins précis.
    """
    connus = list(known_titles)
    brut = normalize_text(title)
    for candidat in connus:                     # correspondance exacte d'abord
        if normalize_text(candidat) == brut:
            return candidat

    tokens = _title_tokens(title)
    if not tokens:
        return None

    meilleur, meilleur_score = None, 0.0
    for candidat in connus:
        ref = _title_tokens(candidat)
        if not ref:
            continue
        commun = len(tokens & ref)
        if not commun:
            continue
        # Recouvrement rapporté au titre du barème : « full stack developer »
        # entièrement contenu dans l'intitulé de l'offre doit scorer 1.
        score = commun / len(ref)
        # Départage : à recouvrement égal, le titre le plus spécifique gagne.
        if score > meilleur_score or (score == meilleur_score and meilleur and len(ref) > len(_title_tokens(meilleur))):
            meilleur, meilleur_score = candidat, score

    return meilleur if meilleur_score >= _TITLE_MATCH_THRESHOLD else None


def build_feature_vector(
    *,
    category: str,
    categories: list[str],
    seniority: int,
    experience_years: float,
    experience_span: float,
    skills_text: str,
    skill_vocab: list[str],
) -> list[float]:
    """
    Vecteur de features, dans l'ordre qui fait contrat entre entraînement et
    inférence :

        [ one-hot(catégories) ] + [ séniorité, expérience, amplitude ] + [ multi-hot(compétences) ]
    """
    vec = [1.0 if category == c else 0.0 for c in categories]
    vec += [float(seniority), float(experience_years), float(experience_span)]
    vec += [float(b) for b in skill_hits(skills_text, skill_vocab)]
    return vec
