"""
Détecteur de CV — étapes 1 à 3 : extraire le texte, créer dataset.csv,
nettoyer le texte.

    cd backend
    python cv_detector/build_dataset.py

Lit `cv_detector/dataset/` :

    cv/{anglais,francais}/      PDF ou DOCX              -> label CV
    not_cv/{anglais,francais}/  TXT (+ not_cv/metadata.csv pour la catégorie)
                                                         -> label NOT_CV
    not_cv_plateforme/{anglais,francais}/
                                offres d'emploi de la plateforme, écrites par
                                export_offres_plateforme.py -> label NOT_CV

et écrit `cv_detector/dataset.csv`, une ligne par document :

    id, label, langue, categorie, fichier, nb_caracteres,
    texte          extraction brute,
    texte_nettoye  texte nettoyé, artefacts de collecte retirés : c'est sur
                   cette colonne que le modèle apprend.

L'extraction est CELLE DE LA PRODUCTION (`app.services.cv_parser`) : le modèle
doit apprendre sur le texte qu'il verra au dépôt, pas sur un autre.

Le CSV contient le texte de CV réels : il est exclu de git et de l'image
Docker. Ce script n'affiche jamais ni texte ni nom de fichier de CV, seulement
des identifiants anonymes (CV_EN_007) que dataset.csv relie aux fichiers.
"""
from __future__ import annotations

import csv
import hashlib
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))

from app.services.cv_detection import nettoyer_texte  # noqa: E402
from app.services.cv_parser import cv_parser  # noqa: E402

DOSSIER = RACINE / "dataset"
SORTIE = RACINE / "dataset.csv"
LANGUES = {"anglais": "en", "francais": "fr"}
LABELS = {"cv": "CV", "not_cv": "NOT_CV"}
# Sources complémentaires de NOT_CV, hors collecte manuelle : dossier -> catégorie.
# `not_cv_plateforme` est écrit par export_offres_plateforme.py.
SOURCES_NOT_CV = {"not_cv_plateforme": "Offre d'emploi"}
EXTENSIONS = {".pdf", ".docx", ".txt"}
# Sous ce seuil, le texte extrait est inexploitable (scan, image). Garder un tel
# document apprendrait au modèle qu'un texte VIDE est un CV — ou n'en est pas un.
MIN_CARACTERES = 150
COLONNES = ["id", "label", "langue", "categorie", "fichier",
            "nb_caracteres", "texte", "texte_nettoye"]

# Artefacts de COLLECTE, mesurés sur ce corpus, qui séparaient presque
# parfaitement les classes sans rien dire de ce qu'est un CV :
#   « example / sample / exemple »  102 non-CV sur 120 (générés), 3 CV ;
#   « fictif / fictive »             37 non-CV (générés), 0 CV ;
#   « company name »                 36 CV sur 46 (gabarits non remplis), 0 non-CV ;
#   « i1 »                           21 CV : un glyphe de gabarit que la
#                                    normalisation Unicode change en « i1 ».
# Laissés en place, ils donnaient une accuracy de 1,000 sur le test : le modèle
# reconnaissait la PROVENANCE des fichiers, pas un CV.
#
# Ils sont retirés APRÈS le nettoyage — « i1 » n'existe qu'une fois le texte
# normalisé — et de TOUS les documents, quelle que soit leur étiquette : un
# retrait qui dépendrait du label ferait fuiter le label dans le prétraitement.
# Ce n'est pas un nettoyage de production : un vrai dépôt ne contient pas ces
# marqueurs, et `nettoyer_texte` reste le seul prétraitement du modèle servi.
ARTEFACTS_DE_COLLECTE = [
    re.compile(r"\b(?:examples?|samples?|exemples?|echantillons?)\b"),
    re.compile(r"\b(?:fictifs?|fictives?|fictitious)\b"),
    re.compile(r"\bcompany name\b"),
    re.compile(r"\bcity ?[,/|-]? ?state\b"),
    re.compile(r"\bi1\b"),
]


def neutraliser_artefacts(texte_nettoye: str) -> tuple[str, int]:
    """Retire les artefacts d'un texte DÉJÀ nettoyé ; rend (texte, nombre de retraits)."""
    retraits = 0
    for motif in ARTEFACTS_DE_COLLECTE:
        texte_nettoye, n = motif.subn(" ", texte_nettoye)
        retraits += n
    return " ".join(texte_nettoye.split()), retraits


def _categories_non_cv() -> dict[str, str]:
    meta = DOSSIER / "not_cv" / "metadata.csv"
    if not meta.exists():
        return {}
    with meta.open(encoding="utf-8-sig", newline="") as flux:
        return {Path(ligne["file"]).name: ligne["category"] for ligne in csv.DictReader(flux)}


def _extraire(chemin: Path) -> str:
    if chemin.suffix.lower() == ".txt":
        return chemin.read_text(encoding="utf-8", errors="replace")
    return cv_parser.extract_text_from_bytes(chemin.read_bytes(), chemin.suffix.lower())


def construire(verbeux: bool = True) -> list[dict]:
    """Construit dataset.csv et rend ses lignes."""
    categories = _categories_non_cv()
    lignes: list[dict] = []
    vus: dict[str, str] = {}
    illisibles: list[str] = []
    doublons: list[tuple[str, str]] = []
    rangs: Counter = Counter()
    artefacts: Counter = Counter()

    sources = [(dossier, label, None) for dossier, label in LABELS.items()]
    sources += [(dossier, "NOT_CV", categorie) for dossier, categorie in SOURCES_NOT_CV.items()]
    for dossier_source, label, categorie_fixe in sources:
        for dossier_langue, langue in LANGUES.items():
            dossier = DOSSIER / dossier_source / dossier_langue
            if not dossier.is_dir():
                continue
            for chemin in sorted(p for p in dossier.iterdir() if p.suffix.lower() in EXTENSIONS):
                rangs[(label, langue)] += 1
                ident = f"{label}_{langue.upper()}_{rangs[(label, langue)]:03d}"
                texte = _extraire(chemin)
                if len(texte.strip()) < MIN_CARACTERES:
                    illisibles.append(ident)
                    continue

                nettoye, retraits = neutraliser_artefacts(nettoyer_texte(texte))
                if retraits:
                    artefacts[label] += 1
                    # Retirer un marqueur rapproche ce qui l'entourait : on
                    # renettoie, pour que la colonne reste un point fixe.
                    nettoye = nettoyer_texte(nettoye)
                # Le vectoriseur rejoue `nettoyer_texte` sur cette colonne, à
                # l'entraînement comme en production. Le rejouer ne doit rien
                # changer, sinon le modèle n'apprendrait pas sur le texte qu'il
                # verra ensuite.
                assert nettoyer_texte(nettoye) == nettoye, f"nettoyage non idempotent : {ident}"

                # Doublons repérés sur le texte NETTOYÉ : un même CV réenregistré
                # sous une autre forme compte aussi. Laissé en double, il pourrait
                # tomber une fois en entraînement et une fois en test — le modèle
                # serait alors évalué sur un document qu'il a déjà vu.
                empreinte = hashlib.sha256(nettoye.encode("utf-8")).hexdigest()
                if empreinte in vus:
                    doublons.append((ident, vus[empreinte]))
                    continue
                vus[empreinte] = ident
                lignes.append({
                    "id": ident,
                    "label": label,
                    "langue": langue,
                    "categorie": "CV" if label == "CV" else (categorie_fixe or categories.get(chemin.name, "?")),
                    "fichier": chemin.relative_to(RACINE).as_posix(),
                    "nb_caracteres": len(texte),
                    "texte": texte,
                    "texte_nettoye": nettoye,
                })

    with SORTIE.open("w", encoding="utf-8-sig", newline="") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=COLONNES)
        ecrivain.writeheader()
        ecrivain.writerows(lignes)

    if verbeux:
        _resume(lignes, illisibles, doublons, artefacts)
    return lignes


def _resume(lignes: list[dict], illisibles: list[str], doublons: list[tuple[str, str]],
            artefacts: Counter) -> None:
    print(f"\ndataset.csv : {len(lignes)} documents -> {SORTIE}")
    print(f"\n{'':10}{'en':>6}{'fr':>6}{'total':>8}")
    for label in LABELS.values():
        en = sum(1 for l in lignes if l["label"] == label and l["langue"] == "en")
        fr = sum(1 for l in lignes if l["label"] == label and l["langue"] == "fr")
        print(f"{label:10}{en:>6}{fr:>6}{en + fr:>8}")

    print("\nLongueur du texte extrait (caractères, médiane) :")
    for label in LABELS.values():
        tailles = [l["nb_caracteres"] for l in lignes if l["label"] == label]
        if tailles:
            print(f"  {label:8} {statistics.median(tailles):>8.0f}   (min {min(tailles)}, max {max(tailles)})")

    categories = Counter(l["categorie"] for l in lignes if l["label"] == "NOT_CV")
    print("\nCatégories NOT_CV : " + ", ".join(f"{c} {n}" for c, n in sorted(categories.items())))
    if illisibles:
        print(f"\nÉcartés, texte illisible (< {MIN_CARACTERES} caractères) : {', '.join(illisibles)}")
    if doublons:
        print("Écartés, doublons : " + ", ".join(f"{d} = {o}" for d, o in doublons))
    print("Artefacts de collecte neutralisés dans : "
          + ", ".join(f"{n} {label}" for label, n in sorted(artefacts.items())))


if __name__ == "__main__":
    construire()
