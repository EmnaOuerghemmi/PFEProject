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

import io
import logging
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status

logger = logging.getLogger(__name__)

CV_ROOT = Path("uploads/cvs")

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Le .doc (Word 97-2003) n'est plus accepté : l'extraction ne lit que le .docx,
# si bien qu'un .doc était accepté au dépôt puis analysé SANS TEXTE — score nul,
# et le candidat n'en savait rien. Mieux vaut le lui dire au moment du dépôt.
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_SIZE_BYTES = 5 * 1024 * 1024
# Un DOCX est une archive ZIP : au-delà de cette taille DÉCOMPRESSÉE, c'est une
# « bombe » de décompression, pas un CV.
MAX_DOCX_DECOMPRESSED_BYTES = 50 * 1024 * 1024


def _extension(upload: UploadFile) -> str:
    return Path(upload.filename or "").suffix.lower()


def type_reel(contenu: bytes) -> Optional[str]:
    """
    Type du fichier d'après son CONTENU — « .pdf », « .docx » — ou None.

    Le nom et le type MIME sont choisis par le client : renommer un exécutable
    en « cv.pdf » suffisait à franchir l'ancien contrôle, qui ne regardait
    qu'eux. La signature, elle, est dans le fichier :
      * PDF  : « %PDF- » dans le premier kilo-octet ;
      * DOCX : une archive ZIP contenant `word/document.xml`, sans macros
               (`word/vbaProject.bin` trahit un .docm renommé) et de taille
               décompressée raisonnable.
    """
    if b"%PDF-" in contenu[:1024]:
        return ".pdf"
    if contenu[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(contenu)) as archive:
                noms = set(archive.namelist())
                decompresse = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile:
            return None
        if ("word/document.xml" in noms and "word/vbaProject.bin" not in noms
                and decompresse <= MAX_DOCX_DECOMPRESSED_BYTES):
            return ".docx"
    return None


async def read_and_validate(upload: UploadFile) -> tuple[bytes, str]:
    """
    Lit le fichier déposé et vérifie que c'est réellement un PDF ou un DOCX.

    Retourne `(contenu, extension)`, l'extension étant celle du type RÉEL : un
    PDF nommé « cv.docx » est enregistré comme le PDF qu'il est.
    """
    extension = _extension(upload)
    # Premier filtre, bon marché, sur ce que DÉCLARE le client : il écarte
    # l'erreur manifeste (une photo) avant toute lecture. Il ne prouve rien.
    if upload.content_type not in ALLOWED_CONTENT_TYPES and extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format non accepté. Déposez un PDF ou un document Word (.pdf, .docx).",
        )

    # Lecture BORNÉE : un octet de plus que le maximum suffit à savoir qu'il est
    # dépassé. L'ancienne lecture intégrale chargeait en mémoire un envoi de
    # n'importe quelle taille avant de le refuser.
    contenu = await upload.read(MAX_SIZE_BYTES + 1)
    if len(contenu) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier trop volumineux : le maximum est de 5 Mo.",
        )
    if not contenu:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier déposé est vide.",
        )

    reel = type_reel(contenu)
    if reel is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier n'est pas un PDF ou un document Word (.docx) valide.",
        )
    return contenu, reel


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
