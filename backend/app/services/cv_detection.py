"""
Détection de CV au dépôt : TF-IDF + régression logistique.

Module PARTAGÉ entre l'entraînement (`cv_detector/`) et la production :

* `nettoyer_texte` est le préprocesseur du vectoriseur TF-IDF. Il est
  enregistré DANS le vectoriseur sauvegardé, par référence à cette fonction :
  le modèle ne peut pas être servi avec un nettoyage différent de celui avec
  lequel il a été entraîné.
* `DetecteurCV` charge le modèle et applique les seuils de décision ;
  `verifier_document` est le point d'entrée des routes de dépôt.

Le nettoyage ne SUPPRIME aucun mot — consigne explicite : les termes qui
structurent un CV (Experience, Education, Skills, Formation, Compétences…)
sont précisément ce qui le distingue d'un autre document. Il MASQUE en
revanche les emails, téléphones, adresses web et années : le modèle apprend
« ce document contient un email », jamais l'email lui-même. C'est un signal
utile, et cela évite que des coordonnées de candidats finissent dans le
vocabulaire du vectoriseur sauvegardé.
"""
import asyncio
import json
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.cv_parser import cv_parser

logger = logging.getLogger(__name__)

# Mots qui structurent un CV ou un justificatif, sous leur forme normalisée
# (minuscules, sans accents). Le nettoyage ne doit jamais les faire disparaître :
# les tests le vérifient.
MOTS_CLES_PRESERVES = (
    "experience", "education", "skills", "formation",
    "competences", "diplome", "attestation",
)

# « dévelop-\npement » -> « développement » : coupure de fin de ligne d'un PDF.
_COUPURE = re.compile(r"(\w)-\n(\w)")
# « E X P E R I E N C E » -> « EXPERIENCE » : titres espacés de certains modèles.
# Sans cela, le découpage en mots du TF-IDF (2 caractères minimum) les ignore.
_LETTRES_ESPACEES = re.compile(r"(?<![^\W\d_])(?:[^\W\d_] ){3,}[^\W\d_](?![^\W\d_])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Un domaine nu n'est une adresse que s'il est suivi d'un chemin
# (« github.com/nom ») : « ASP.NET » ou « Node.js » sont des compétences, et
# « 15.5/20 » une note de relevé, pas une URL.
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}/\S*")
_ANNEE = re.compile(r"\b(?:19|20)\d{2}\b")
# Après le masquage des années : « 2019 - 2022 » ne doit pas passer pour un numéro.
# Tout espacement est admis entre les chiffres : l'extraction d'un PDF y laisse
# souvent tabulations et retours à la ligne. Avec les seuls espaces, un numéro
# ainsi découpé échappait au masquage — et restait en clair dans le texte.
_TELEPHONE = re.compile(r"(?<!\w)(?:\+|00)?\d(?:[\s.\-()/]*\d){7,14}(?!\w)")
_ESPACES = re.compile(r"\s+")


def nettoyer_texte(texte: str) -> str:
    """
    Normalise un texte extrait SANS en retirer le contenu.

    Rend aussi homogènes les textes issus d'un PDF et d'un fichier texte :
    ligatures, coupures de ligne et titres espacés sont des marques du FORMAT,
    et un modèle qui les apprendrait reconnaîtrait le format au lieu du contenu.
    Minuscules et accents sont traités ici parce qu'un `preprocessor` remplace
    l'étape équivalente du vectoriseur.

    IDEMPOTENTE par construction : la passe est rejouée jusqu'à stabilité. Le
    vectoriseur l'applique à des textes d'entraînement déjà nettoyés ; si la
    rejouer changeait encore le texte, le modèle n'apprendrait pas sur celui
    qu'il voit en production. Une passe peut en effet révéler un motif que la
    précédente laissait passer — des espaces fusionnés en fin de passe qui
    forment un titre espacé, par exemple.
    """
    if not texte:
        return ""
    t = _une_passe(texte)
    for _ in range(3):              # en pratique, stable dès la deuxième passe
        suivant = _une_passe(t)
        if suivant == t:
            break
        t = suivant
    return t


def _une_passe(texte: str) -> str:
    t = unicodedata.normalize("NFKC", texte)          # ligatures « ﬁ », espaces insécables
    t = _COUPURE.sub(r"\1\2", t)
    t = _LETTRES_ESPACEES.sub(lambda m: m.group(0).replace(" ", ""), t)
    t = _EMAIL.sub(" __email__ ", t)
    t = _URL.sub(" __url__ ", t)
    t = _ANNEE.sub(" __annee__ ", t)
    t = _TELEPHONE.sub(" __telephone__ ", t)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return _ESPACES.sub(" ", t.lower()).strip()


# ── Décision ──────────────────────────────────────────────────────────────────

MESSAGE_REFUS = "❌ Le document envoyé ne semble pas être un CV. Veuillez importer votre CV."
MESSAGE_ILLISIBLE = (
    "Le texte de ce document n'a pas pu être lu (document scanné, image ou PDF "
    "protégé). Importez votre CV au format PDF texte ou Word (.docx)."
)


@dataclass(frozen=True)
class VerdictCV:
    # « accepte », « incertain » (accepté), « refuse », « illisible »,
    # ou « non_verifie » (détecteur désactivé ou modèle absent).
    decision: str
    probabilite_cv: Optional[float] = None
    message: Optional[str] = None

    @property
    def bloquant(self) -> bool:
        return self.decision in ("refuse", "illisible")


class DetecteurCV:
    FICHIER_MODELE = "cv_classifier.joblib"
    FICHIER_VECTORISEUR = "tfidf_vectorizer.joblib"
    FICHIER_METADONNEES = "metadata.json"

    def __init__(self, dossier: Optional[Union[str, Path]] = None) -> None:
        self.dossier = Path(dossier or settings.CV_DETECTOR_MODEL_DIR)
        self.metadonnees: dict = {}
        self._verrou = threading.Lock()
        self._tente = False
        self._vectoriseur = None
        self._modele = None
        self._indice_cv = 0

    def _charger(self) -> bool:
        """Charge le modèle une seule fois ; False s'il est absent ou illisible."""
        with self._verrou:
            if self._tente:
                return self._modele is not None
            self._tente = True
            try:
                import joblib
                self._vectoriseur = joblib.load(self.dossier / self.FICHIER_VECTORISEUR)
                self._modele = joblib.load(self.dossier / self.FICHIER_MODELE)
                self._indice_cv = list(self._modele.classes_).index("CV")
                meta = self.dossier / self.FICHIER_METADONNEES
                if meta.exists():
                    self.metadonnees = json.loads(meta.read_text(encoding="utf-8"))
                logger.info("Détecteur de CV chargé (entraîné le %s).",
                            self.metadonnees.get("entraine_le", "?"))
            except FileNotFoundError:
                logger.warning("Détecteur de CV : aucun modèle dans « %s » — dépôts acceptés "
                               "sans vérification. Lancer cv_detector/train.py.", self.dossier)
                self._vectoriseur = self._modele = None
            except Exception as exc:
                logger.warning("Détecteur de CV : chargement impossible (%s) — dépôts acceptés "
                               "sans vérification.", type(exc).__name__)
                self._vectoriseur = self._modele = None
            return self._modele is not None

    @property
    def disponible(self) -> bool:
        return self._charger()

    def probabilite_cv(self, texte: str) -> Optional[float]:
        """Probabilité que le texte soit un CV, ou None sans modèle."""
        if not self._charger():
            return None
        vecteur = self._vectoriseur.transform([texte])
        return float(self._modele.predict_proba(vecteur)[0][self._indice_cv])

    def evaluer(self, texte: str) -> VerdictCV:
        if not settings.CV_DETECTOR_ENABLED:
            return VerdictCV("non_verifie")
        # Contrôle indépendant du modèle : un document sans texte ne peut être
        # ni vérifié ni analysé — l'accepter, c'est garantir un score nul.
        if len((texte or "").strip()) < settings.CV_DETECTOR_MIN_TEXT_CHARS:
            return VerdictCV("illisible", None, MESSAGE_ILLISIBLE)
        probabilite = self.probabilite_cv(texte)
        if probabilite is None:
            return VerdictCV("non_verifie")
        if probabilite >= settings.CV_DETECTOR_ACCEPT_THRESHOLD:
            return VerdictCV("accepte", probabilite)
        if probabilite < settings.CV_DETECTOR_REJECT_THRESHOLD:
            return VerdictCV("refuse", probabilite, MESSAGE_REFUS)
        return VerdictCV("incertain", probabilite)


detecteur_cv = DetecteurCV()


def _verifier(contenu: bytes, extension: str) -> VerdictCV:
    return detecteur_cv.evaluer(cv_parser.extract_text_from_bytes(contenu, extension))


async def verifier_document(contenu: bytes, extension: str) -> VerdictCV:
    """
    Vérifie qu'un fichier déposé est un CV, AVANT son enregistrement.

    Lève une HTTPException 400 portant le message destiné au candidat si le
    document est refusé ou illisible. Extraction et modèle s'exécutent dans un
    thread : un PDF de quelques pages prend plusieurs centaines de
    millisecondes, qui figeraient sinon toute l'API.

    Le journal ne contient que la décision et la probabilité : ni le texte, ni
    le nom du fichier, qui porte souvent celui du candidat.
    """
    verdict = await asyncio.to_thread(_verifier, contenu, extension)
    logger.info(
        "Détection de CV : %s (probabilité %s).", verdict.decision,
        "n/a" if verdict.probabilite_cv is None else f"{verdict.probabilite_cv:.2f}",
    )
    if verdict.bloquant:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=verdict.message)
    return verdict
