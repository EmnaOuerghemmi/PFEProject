"""
Détecteur de CV — prédiction sur des documents jamais vus.

    cd backend
    python cv_detector/predict.py "C:\\Users\\...\\mon_cv.pdf" lettre.docx note.txt

Emprunte EXACTEMENT le chemin de l'API de dépôt : extraction de production
(`cv_parser`), nettoyage, TF-IDF, régression logistique, puis les seuils de
`config.py`. Ce que ce script affiche est donc ce que vivra le candidat.

Rien n'est journalisé ni enregistré : le texte des documents ne quitte pas la
mémoire du processus.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))

from app.services.cv_detection import DetecteurCV  # noqa: E402
from app.services.cv_parser import cv_parser  # noqa: E402

DECISIONS = {
    "accepte": "accepté",
    "incertain": "accepté (zone incertaine)",
    "refuse": "REFUSÉ",
    "illisible": "REFUSÉ — texte illisible",
    "non_verifie": "non vérifié",
}


def _texte(chemin: Path) -> str | None:
    extension = chemin.suffix.lower()
    if extension == ".txt":
        return chemin.read_text(encoding="utf-8", errors="replace")
    if extension in (".pdf", ".docx"):
        return cv_parser.extract_text_from_bytes(chemin.read_bytes(), extension)
    return None


def main(chemins: list[str]) -> None:
    detecteur = DetecteurCV(RACINE / "models")
    if not detecteur.disponible:
        sys.exit("Aucun modèle dans cv_detector/models : lancer d'abord cv_detector/train.py.")

    for brut in chemins:
        chemin = Path(brut)
        if not chemin.is_file():
            print(f"{chemin.name} -> introuvable")
            continue
        texte = _texte(chemin)
        if texte is None:
            print(f"{chemin.name} -> format non pris en charge ({chemin.suffix})")
            continue

        verdict = detecteur.evaluer(texte)
        p = verdict.probabilite_cv
        if p is None:
            print(f"{chemin.name} -> {DECISIONS[verdict.decision]}")
            continue
        classe, confiance = ("CV", p) if p >= 0.5 else ("NOT_CV", 1 - p)
        print(f"{chemin.name} -> {classe} {confiance:.0%}"
              f"   (probabilité CV {p:.2f} ; décision à l'API : {DECISIONS[verdict.decision]})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
