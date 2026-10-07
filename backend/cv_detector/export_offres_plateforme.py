"""
Détecteur de CV — exporte les offres d'emploi de la plateforme comme exemples NOT_CV.

    cd backend
    python cv_detector/export_offres_plateforme.py

Pourquoi : une offre d'emploi est le non-CV le plus proche d'un CV — mêmes
compétences, mêmes années d'expérience, même vocabulaire. Le dataset collecté
n'en contenait aucune. Mesuré : avec l'augmentation par extraits, le modèle
acceptait une offre d'emploi comme un CV à 92 % ; il ne pouvait pas apprendre
une différence qu'il n'avait jamais vue.

Écrit `dataset/not_cv_plateforme/{francais,anglais}/OFFRE_xxx.txt`, À PART des
dossiers collectés à la main, pour que leur provenance reste lisible. Le
dossier est vidé puis réécrit : relancer le script reflète l'état de la base.

Une offre d'emploi ne contient pas de données personnelles de candidat ;
d'éventuelles coordonnées de recruteur sont masquées par le nettoyage.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))

SORTIE = RACINE / "dataset" / "not_cv_plateforme"
MIN_CARACTERES = 150

_MOTS_FR = re.compile(r"\b(?:le|la|les|des|du|et|pour|avec|une|dans|vous|nous)\b", re.IGNORECASE)
_MOTS_EN = re.compile(r"\b(?:the|and|of|to|for|with|you|we|our|in|is|are)\b", re.IGNORECASE)


def _langue(texte: str) -> str:
    """Langue majoritaire, par décompte de mots-outils — suffisant pour deux langues."""
    return "francais" if len(_MOTS_FR.findall(texte)) >= len(_MOTS_EN.findall(texte)) else "anglais"


async def _offres() -> list[str]:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.models.recruitment import JobOffer

    async with AsyncSessionLocal() as db:
        lignes = (await db.execute(
            select(JobOffer.title, JobOffer.description, JobOffer.required_skills)
        )).all()
    textes = []
    for titre, description, competences in lignes:
        texte = "\n\n".join(filter(None, [
            (titre or "").strip(),
            (description or "").strip(),
            ("Compétences requises : " + ", ".join(competences)) if competences else "",
        ]))
        if len(texte) >= MIN_CARACTERES:
            textes.append(texte)
    return textes


def main() -> None:
    textes = asyncio.run(_offres())
    for langue in ("francais", "anglais"):
        dossier = SORTIE / langue
        dossier.mkdir(parents=True, exist_ok=True)
        for ancien in dossier.glob("OFFRE_*.txt"):
            ancien.unlink()
    compte = {"francais": 0, "anglais": 0}
    for texte in textes:
        langue = _langue(texte)
        compte[langue] += 1
        (SORTIE / langue / f"OFFRE_{compte[langue]:03d}.txt").write_text(texte, encoding="utf-8")
    print(f"{len(textes)} offres exportées -> {SORTIE} "
          f"(français {compte['francais']}, anglais {compte['anglais']})")


if __name__ == "__main__":
    main()
