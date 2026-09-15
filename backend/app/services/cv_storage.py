"""
Stockage des CV — validation, écriture et copie des fichiers.

Un CV vit désormais à deux endroits, et la distinction est volontaire :

* **Le CV du profil** (`Candidate.cv_path`) — celui que le candidat gère depuis
  son espace. Il en existe UN par candidat, remplacé à chaque dépôt.
* **Le CV de la candidature** (`Application.cv_file_path`) — une COPIE figée au
  moment du dépôt. C'est elle qui est analysée et scorée.

Pourquoi une copie plutôt qu'une référence : le candidat peut remplacer son CV
de profil à tout moment. Si les candidatures pointaient dessus, une mise à jour
réécrirait rétroactivement le dossier sur lequel le RH a décidé, et les scores
déjà calculés ne correspondraient plus au document analysé. La copie garantit
qu'une candidature reste le reflet de ce qui a été envoyé ce jour-là.

La validation (type, extension, taille) était jusqu'ici écrite en dur dans
l'endpoint de candidature ; elle est centralisée ici pour que le dépôt depuis le
profil et le dépôt depuis une candidature ne puissent pas diverger.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status

logger = logging.getLogger(__name__)

CV_ROOT = Path("uploads/cvs")

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_SIZE_BYTES = 5 * 1024 * 1024


def _extension(upload: UploadFile) -> str:
    return Path(upload.filename or "").suffix.lower()


async def read_and_validate(upload: UploadFile) -> tuple[bytes, str]:
    """
    Lit le fichier en mémoire après contrôle du type puis de la taille.

    Le contrôle de type précède la lecture : inutile de charger 5 Mo d'une image
    avant de la refuser. Retourne `(contenu, extension)`.
    """
    extension = _extension(upload)
    if upload.content_type not in ALLOWED_CONTENT_TYPES and extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format non accepté. Déposez un PDF ou un document Word (.pdf, .doc, .docx).",
        )

    contenu = await upload.read()
    if len(contenu) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fichier trop volumineux : {len(contenu) / 1048576:.1f} Mo pour un maximum de 5 Mo.",
        )
    if not contenu:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier déposé est vide.",
        )
    return contenu, extension or ".pdf"


def _write(chemin: Path, contenu: bytes) -> str:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return chemin.as_posix()


def store_profile_cv(user_id, contenu: bytes, extension: str) -> str:
    """
    Écrit le CV du profil et renvoie son chemin.

    Le nom porte un suffixe aléatoire plutôt que le seul identifiant de
    l'utilisateur : sans lui, un remplacement réécrirait le fichier à la même
    adresse et les caches (navigateur, CDN) continueraient de servir l'ancien
    document. L'ancien fichier est supprimé par l'appelant via `discard`.
    """
    nom = f"profil_{user_id}_{uuid.uuid4().hex[:8]}{extension}"
    return _write(CV_ROOT / nom, contenu)


def store_application_cv(user_id, job_id, contenu: bytes, extension: str) -> str:
    """Écrit la copie propre à une candidature."""
    return _write(CV_ROOT / f"{user_id}_{job_id}{extension}", contenu)


def copy_profile_cv_to_application(profile_path: str, user_id, job_id) -> str:
    """
    Duplique le CV du profil pour une candidature.

    Lève 400 si le fichier référencé a disparu du disque : mieux vaut demander
    au candidat de redéposer son CV que d'enregistrer une candidature dont le
    document est introuvable — elle échouerait plus tard, à l'analyse, sans que
    personne ne comprenne pourquoi.
    """
    source = Path(profile_path)
    if not source.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Votre CV enregistré est introuvable. Merci de le déposer à nouveau.",
        )
    cible = CV_ROOT / f"{user_id}_{job_id}{source.suffix.lower() or '.pdf'}"
    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, cible)
    return cible.as_posix()


def discard(chemin: Optional[str], *, keep: Optional[str] = None) -> None:
    """
    Supprime un fichier CV devenu inutile, sans jamais faire échouer l'appelant.

    `keep` protège un chemin encore référencé — typiquement quand une
    candidature pointe sur le même fichier que le profil.
    """
    if not chemin or chemin == keep:
        return
    try:
        cible = Path(chemin)
        if cible.exists():
            cible.unlink()
    except OSError as exc:  # pragma: no cover - dépend du système de fichiers
        logger.warning("Suppression du CV impossible (%s) : %s", chemin, exc)
