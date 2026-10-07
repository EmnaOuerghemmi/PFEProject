"""
Masquage des charges utiles avant envoi à un traceur externe.

RAISON D'ÊTRE. Le pipeline tracé interroge des CV. Une trace brute contiendrait
nom, téléphone, employeurs, diplômes — les données personnelles que le projet
interdit de faire sortir. Un outil d'observabilité est un journal : la règle
s'y applique sans exception.

PRINCIPE. Par défaut, rien du contenu ne sort. Ce qui sort est un DESCRIPTEUR :
longueur, empreinte tronquée, nombre d'éléments. C'est suffisant pour
diagnostiquer, insuffisant pour identifier quelqu'un.

L'empreinte mérite un mot. Deux questions identiques produisent la même
empreinte : on peut donc suivre un cache, repérer une question posée cent fois,
comparer deux traces — sans jamais lire la question. Elle est tronquée à
12 caractères hexadécimaux : assez pour distinguer, trop court pour tenter une
attaque par dictionnaire sur un corpus de questions RH.
"""
from __future__ import annotations

import hashlib
from typing import Any

from app.core.config import settings

# Marqueur présent dans toute valeur masquée. Permet de vérifier d'un coup
# d'œil, dans l'interface de traçage, qu'aucun contenu n'a fui.
MASK_FLAG = "_masked"


def empreinte(texte: str) -> str:
    """Empreinte courte et stable d'un texte, pour corréler sans révéler."""
    return hashlib.sha256((texte or "").encode("utf-8")).hexdigest()[:12]


def masquer_texte(texte: str | None, *, etiquette: str = "text") -> dict[str, Any]:
    """
    Descripteur d'un texte. Ne renvoie le texte lui-même que si le traçage du
    contenu est explicitement autorisé, et tronqué dans ce cas.
    """
    texte = texte or ""
    descripteur: dict[str, Any] = {
        "kind": etiquette,
        "chars": len(texte),
        "sha256_12": empreinte(texte),
    }
    if settings.LANGFUSE_TRACE_CONTENT:
        limite = settings.LANGFUSE_CONTENT_MAX_CHARS
        descripteur["content"] = texte[:limite]
        descripteur["truncated"] = len(texte) > limite
    else:
        descripteur[MASK_FLAG] = True
    return descripteur


def masquer_passages(passages: list[str] | None, *, etiquette: str = "passages") -> dict[str, Any]:
    """
    Descripteur d'une liste de passages récupérés.

    Les longueurs individuelles sont conservées : une récupération qui ne
    ramène que des passages de 20 caractères signale un découpage défaillant,
    et ce diagnostic ne demande pas de lire les passages.
    """
    passages = passages or []
    descripteur: dict[str, Any] = {
        "kind": etiquette,
        "count": len(passages),
        "chars_total": sum(len(p or "") for p in passages),
        "chars_each": [len(p or "") for p in passages[:20]],
    }
    if settings.LANGFUSE_TRACE_CONTENT:
        limite = settings.LANGFUSE_CONTENT_MAX_CHARS
        descripteur["content"] = [(p or "")[:limite] for p in passages[:10]]
    else:
        descripteur[MASK_FLAG] = True
    return descripteur


def masquer_identifiant(valeur: Any) -> str | None:
    """
    Un identifiant technique (UUID de candidature) n'est pas une donnée
    personnelle en soi, mais il désigne une personne. On n'en garde qu'une
    empreinte : deux traces de la même candidature restent corrélables, sans
    qu'un lecteur du traceur puisse remonter à la fiche.
    """
    if valeur is None:
        return None
    return empreinte(str(valeur))


def filet_de_securite(*, data: Any, **_: Any) -> Any:
    """
    Masque de dernier recours, branché sur le SDK Langfuse lui-même.

    POURQUOI UN SECOND FILTRE. Tout ce qui est tracé passe déjà par les
    fonctions ci-dessus, appelées explicitement à chaque site. Mais c'est une
    discipline, et une discipline s'oublie : il suffit d'un `metadata={"cv":
    texte}` ajouté un jour de fatigue pour qu'un CV parte. Ce masque-ci
    s'applique à TOUT ce que le SDK envoie, y compris ce que le SDK collecte
    de lui-même, et il ne dépend d'aucune vigilance au site d'appel.

    Sa règle est simple et brutale : au-delà d'une longueur qui ne peut plus
    être un libellé technique, une chaîne est remplacée par son descripteur.
    Un identifiant, un statut ou un nom d'étape passent ; un paragraphe de CV
    ne passe pas.

    Inactif lorsque le traçage du contenu est explicitement autorisé — dans ce
    cas la décision a été prise en connaissance de cause, et ce filet n'a plus
    lieu d'être.
    """
    if settings.LANGFUSE_TRACE_CONTENT:
        return data
    return _elaguer(data, profondeur=0)


# Au-delà de cette longueur, une chaîne n'est plus un libellé technique.
SEUIL_TEXTE_LIBRE = 120
_PROFONDEUR_MAX = 6


def _elaguer(valeur: Any, *, profondeur: int) -> Any:
    """Parcours récursif du corps d'une trace, en élaguant le texte libre."""
    if profondeur > _PROFONDEUR_MAX:
        return {MASK_FLAG: True, "kind": "depth_limit"}
    if isinstance(valeur, str):
        if len(valeur) > SEUIL_TEXTE_LIBRE:
            return masquer_texte(valeur, etiquette="long_text")
        return valeur
    if isinstance(valeur, dict):
        # Un descripteur déjà masqué est laissé tel quel : le remasquer
        # écraserait les longueurs et les empreintes, qui sont l'information
        # utile.
        if valeur.get(MASK_FLAG) is True:
            return valeur
        return {c: _elaguer(v, profondeur=profondeur + 1) for c, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_elaguer(v, profondeur=profondeur + 1) for v in valeur]
    return valeur


def metadonnees_sures(**kwargs: Any) -> dict[str, Any]:
    """
    Filtre de dernier recours. N'accepte que des types dont on est certain
    qu'ils ne transportent pas de texte libre : nombres, booléens, None, et
    chaînes courtes appartenant à une liste blanche de vocabulaire technique.

    Toute chaîne non reconnue est remplacée par son descripteur. C'est
    volontairement strict : un champ ajouté par mégarde doit être masqué par
    défaut, pas exposé par défaut.
    """
    VOCABULAIRE_SUR = {
        "hit", "miss", "native", "fallback", "cache", "kb", "cv",
        "ok", "empty", "not_found", "not_analyzed", "low_confidence",
        "sentence-transformers", "hash", "pgvector", "python",
    }
    propre: dict[str, Any] = {}
    for cle, valeur in kwargs.items():
        if valeur is None or isinstance(valeur, (int, float, bool)):
            propre[cle] = valeur
        elif isinstance(valeur, str) and valeur in VOCABULAIRE_SUR:
            propre[cle] = valeur
        elif isinstance(valeur, (list, tuple)) and all(
            isinstance(v, (int, float, bool)) for v in valeur
        ):
            propre[cle] = list(valeur)
        elif isinstance(valeur, str):
            propre[cle] = masquer_texte(valeur, etiquette=cle)
        else:
            propre[cle] = {"kind": type(valeur).__name__, MASK_FLAG: True}
    return propre
