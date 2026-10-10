"""
Détecteur de CV — démonstration pas à pas.

Chaque étape est une fonction, exécutable seule :

    cd backend
    python cv_detector/demo_detecteur.py dataset        # 1. reconstruire dataset.csv (nouveaux CV pris en compte)
    python cv_detector/demo_detecteur.py entrainer      # 2. réentraîner et sauvegarder le modèle
    python cv_detector/demo_detecteur.py matrice        # 3. matrice de confusion (figure)
    python cv_detector/demo_detecteur.py refus          # 4. refus d'un document non-CV au dépôt (figure)
    python cv_detector/demo_detecteur.py refus mon_document.pdf
    python cv_detector/demo_detecteur.py api            # 5. même dépôt, envoyé à l'API qui tourne
    python cv_detector/demo_detecteur.py tout           # 2 → 3 → 4 à la suite

Dans VS Code ou PyCharm, les blocs `# %%` s'exécutent aussi un par un
(« Run Cell » ; nécessite `pip install ipykernel` pour VS Code).

Ajouter des CV : déposer les PDF / DOCX dans
    cv_detector/dataset/cv/anglais/   ou   cv_detector/dataset/cv/francais/
puis lancer `entrainer` (qui reconstruit le dataset lui-même).

Rien ici n'affiche le texte ni le nom d'un CV : seulement des totaux, des
décisions et des probabilités.
"""
# %% Préparation
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))
sys.path.insert(0, str(RACINE))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.cv_detection import DetecteurCV, VerdictCV  # noqa: E402
from app.services.cv_parser import cv_parser  # noqa: E402

ASSETS = RACINE.parent.parent / "report" / "assets"
LOGO = RACINE.parent.parent / "frontend" / "public" / "logo.png"
FONTS = Path(r"C:\Windows\Fonts")
API = "http://localhost:8000/api/v1/recruitment/cv/verification"

#: Document de démonstration : une facture, sans aucune donnée personnelle.
EXEMPLE_NON_CV = """FACTURE N° 2026-0412
Date d'émission : 12 septembre 2026
Société cliente : Atelier Numérique SARL
Désignation                       Quantité   Prix unitaire   Total HT
Maintenance du parc informatique      1         450,00        450,00
Licence logicielle annuelle           3         120,00        360,00
Total HT : 810,00 TND
TVA 19 % : 153,90 TND
Total TTC : 963,90 TND
Conditions de paiement : virement à 30 jours fin de mois.
Pénalités de retard : trois fois le taux d'intérêt légal.
Merci de rappeler le numéro de facture lors du règlement."""


def _afficher(chemin: Path) -> None:
    """Ouvre l'image avec la visionneuse du système."""
    try:
        Image.open(chemin).show()
    except Exception:  # pragma: no cover - dépend de l'environnement
        pass
    print(f"Figure : {chemin}")


def _en_pdf(texte: str) -> bytes:
    """Rend un texte en PDF, pour le relire exactement comme un dépôt réel."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    tampon = BytesIO()
    style = getSampleStyleSheet()["Normal"]
    blocs = [Paragraph(escape(ligne), style) for ligne in texte.splitlines() if ligne.strip()]
    SimpleDocTemplate(tampon, pagesize=A4).build(blocs)
    return tampon.getvalue()


def _document(chemin: str | None) -> tuple[str, bytes, str]:
    """(nom affiché, contenu, extension) du document à tester."""
    if chemin is None:
        return "facture.pdf (exemple)", _en_pdf(EXEMPLE_NON_CV), ".pdf"
    fichier = Path(chemin)
    extension = fichier.suffix.lower()
    if extension not in (".pdf", ".docx"):
        raise SystemExit("Le dépôt n'accepte que les fichiers .pdf et .docx.")
    return f"document{extension}", fichier.read_bytes(), extension


# %% 1. Dataset
def etape_1_dataset() -> None:
    """Reconstruit dataset.csv depuis cv_detector/dataset/ et affiche sa composition."""
    import pandas as pd
    from build_dataset import construire

    construire(verbeux=True)
    df = pd.read_csv(RACINE / "dataset.csv", encoding="utf-8-sig")
    print("\nComposition du dataset (documents par classe et par langue) :")
    print(pd.crosstab(df["label"], df["langue"], margins=True, margins_name="total").to_string())


# %% 2. Entraînement
def etape_2_entrainer() -> None:
    """Réentraîne le modèle (dataset, découpage, TF-IDF, régression, seuils) et le sauvegarde."""
    import train
    train.main()
    print("\nModèle sauvegardé dans cv_detector/models/. "
          "Redémarrez l'API pour qu'elle charge ce nouveau modèle.")


# %% 3. Matrice de confusion
def etape_3_matrice() -> None:
    """Évalue le modèle sauvegardé sur le jeu de test et dessine la matrice de confusion."""
    from confusion_matrix import CLASSES, LIBELLES, dessiner, evaluer

    matrice, metriques = evaluer()
    print(f"{'':14}{'prédit CV':>12}{'prédit Non-CV':>16}")
    for i, classe in enumerate(CLASSES):
        print(f"{'réel ' + LIBELLES[classe]:14}{matrice[i][0]:>12}{matrice[i][1]:>16}")
    print("   ".join(f"{k} {v:.2f}" for k, v in metriques.items()))
    _afficher(dessiner(matrice, metriques))


# %% 4. Refus d'un document non-CV au dépôt
def etape_4_refus(chemin: str | None = None) -> VerdictCV:
    """
    Passe un document par la MÊME vérification que le dépôt de la plateforme :
    extraction du texte, puis décision du détecteur (refusé / incertain / accepté).
    """
    nom, contenu, extension = _document(chemin)
    texte = cv_parser.extract_text_from_bytes(contenu, extension)
    verdict = DetecteurCV().evaluer(texte)        # instance neuve : relit le dernier modèle sauvegardé

    proba = "n/a" if verdict.probabilite_cv is None else f"{verdict.probabilite_cv:.2f}"
    print(f"Document     : {nom}")
    print(f"Probabilité  : {proba}  (refus < {settings.CV_DETECTOR_REJECT_THRESHOLD:.2f}, "
          f"accepté ≥ {settings.CV_DETECTOR_ACCEPT_THRESHOLD:.2f})")
    print(f"Décision     : {verdict.decision}")
    if verdict.bloquant:
        print(f"Réponse API  : 400 — {verdict.message}")
    _afficher(_dessiner_verdict(nom, verdict))
    return verdict


# %% 5. Le même dépôt, envoyé à l'API
def etape_5_api(chemin: str | None = None) -> None:
    """Envoie le document à POST /recruitment/cv/verification (API locale lancée)."""
    import httpx

    nom, contenu, extension = _document(chemin)
    types = {".pdf": "application/pdf",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    try:
        reponse = httpx.post(API, files={"cv_file": (f"document{extension}", contenu, types[extension])},
                             timeout=60)
    except httpx.HTTPError as exc:
        raise SystemExit(f"API injoignable ({type(exc).__name__}) : lancez-la sur le port 8000.")
    print(f"Document : {nom}")
    print(f"HTTP {reponse.status_code}")
    print(reponse.json())


# ── Figure du verdict ────────────────────────────────────────────────────────
S = 2
INK, SOFT, MUTED = "#0F2440", "#1E3A5F", "#5B6B85"
TONS = {
    "refuse": ("Refusé", "#E5484D", "#FDECEE"),
    "illisible": ("Illisible", "#E5484D", "#FDECEE"),
    "incertain": ("Incertain — accepté", "#D97706", "#FEF3E2"),
    "accepte": ("Accepté", "#23985A", "#EAF7EF"),
    "non_verifie": ("Non vérifié", "#5B6B85", "#F1F4F8"),
}


def _dessiner_verdict(nom: str, verdict: VerdictCV) -> Path:
    W, H = 1200, 640
    img = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(img)
    P = lambda *v: [int(x * S) for x in v]                                       # noqa: E731
    f = lambda nom_police, t: ImageFont.truetype(str(FONTS / nom_police), int(t * S))  # noqa: E731
    texte = lambda x, y, s, font, fill=INK, anchor="la": d.text(P(x, y), s, font=font, fill=fill, anchor=anchor)  # noqa: E731
    largeur = lambda s, font: d.textlength(s, font=font) / S                     # noqa: E731

    # En-tête
    logo = Image.open(LOGO).convert("RGBA").resize((int(56 * S), int(56 * S)), Image.LANCZOS)
    t1, t2 = "PIQBIT", "Refus d'un document non-CV au dépôt"
    f1, f2 = f("seguibl.ttf", 36), f("seguisb.ttf", 29)
    total = 56 + 16 + largeur(t1, f1) + 30 + largeur(t2, f2)
    x = (W - total) / 2
    img.paste(logo, (int(x * S), int(26 * S)), logo)
    x += 72
    texte(x, 54, t1, f1, "#0B2A3C", "lm")
    x += largeur(t1, f1) + 15
    d.line(P(x, 32, x, 76), fill="#0B2A3C", width=int(3 * S))
    texte(x + 15, 54, t2, f2, "#123B6B", "lm")

    libelle, couleur, fond = TONS.get(verdict.decision, TONS["non_verifie"])

    # Flux : document → détecteur → décision
    y0, hb = 130, 120
    blocs = [("Document déposé", nom, "#2B7BD8", "#E8F2FD"),
             ("Détecteur de CV", "TF-IDF + régression logistique", "#7B4FD0", "#F3EEFC"),
             ("Décision", libelle, couleur, fond)]
    lb, ecart = 300, 75
    xb = (W - (3 * lb + 2 * ecart)) / 2
    for i, (titre, sous, c, bg) in enumerate(blocs):
        bx = xb + i * (lb + ecart)
        d.rounded_rectangle(P(bx, y0, bx + lb, y0 + hb), radius=int(20 * S), fill=bg, outline=c, width=int(2 * S))
        texte(bx + lb / 2, y0 + 42, titre, f("segoeuib.ttf", 23), c, "mm")
        texte(bx + lb / 2, y0 + 80, sous, f("seguisb.ttf", 18), SOFT, "mm")
        if i < 2:
            ax = bx + lb + 12
            d.line(P(ax, y0 + hb / 2, ax + ecart - 30, y0 + hb / 2), fill=SOFT, width=int(4 * S))
            d.polygon(P(ax + ecart - 24, y0 + hb / 2, ax + ecart - 40, y0 + hb / 2 - 10,
                        ax + ecart - 40, y0 + hb / 2 + 10), fill=SOFT)

    # Jauge de probabilité avec les deux seuils
    gx0, gx1, gy = 150, W - 150, 360
    refus, accepte = settings.CV_DETECTOR_REJECT_THRESHOLD, settings.CV_DETECTOR_ACCEPT_THRESHOLD
    zones = [(0, refus, "#E5484D", "refus"), (refus, accepte, "#F5A524", "incertain"),
             (accepte, 1, "#23985A", "accepté")]
    for a, b, c, nom_zone in zones:
        d.rectangle(P(gx0 + (gx1 - gx0) * a, gy, gx0 + (gx1 - gx0) * b, gy + 26), fill=c)
        texte(gx0 + (gx1 - gx0) * (a + b) / 2, gy + 52, nom_zone, f("seguisb.ttf", 18), MUTED, "mm")
    for s in (0.0, refus, accepte, 1.0):
        if verdict.probabilite_cv is not None and abs(s - verdict.probabilite_cv) < 0.06:
            continue                      # le repère de probabilité masquerait la graduation
        xs = gx0 + (gx1 - gx0) * s
        texte(xs, gy - 18, f"{s:.2f}".replace(".", ","), f("segoeui.ttf", 16), MUTED, "mm")
    texte(gx0 - 20, gy + 13, "P(CV)", f("segoeuib.ttf", 18), SOFT, "rm")
    if verdict.probabilite_cv is not None:
        xp = gx0 + (gx1 - gx0) * verdict.probabilite_cv
        d.polygon(P(xp - 13, gy - 44, xp + 13, gy - 44, xp, gy - 26), fill=INK)
        d.line(P(xp, gy - 28, xp, gy + 34), fill=INK, width=int(4 * S))
        etiquette = f"{verdict.probabilite_cv:.2f}".replace(".", ",")
        fe = f("seguibl.ttf", 22)
        le = largeur(etiquette, fe) + 26
        d.rounded_rectangle(P(xp - le / 2, gy - 84, xp + le / 2, gy - 50), radius=int(17 * S), fill=INK)
        texte(xp, gy - 67, etiquette, fe, "white", "mm")

    # Réponse renvoyée au candidat
    ry = 470
    d.rounded_rectangle(P(150, ry, W - 150, ry + 120), radius=int(18 * S), fill=fond, outline=couleur, width=int(2 * S))
    if verdict.bloquant:
        texte(180, ry + 36, "HTTP 400  ·  document non enregistré", f("segoeuib.ttf", 20), couleur, "lm")
        message = (verdict.message or "").replace("❌", "").strip()
        texte(180, ry + 80, message, f("seguisb.ttf", 19), INK, "lm")
    else:
        texte(180, ry + 36, "HTTP 200  ·  document accepté", f("segoeuib.ttf", 20), couleur, "lm")
        texte(180, ry + 80, "Le dépôt se poursuit : enregistrement puis analyse du CV.", f("seguisb.ttf", 19), INK, "lm")

    ASSETS.mkdir(parents=True, exist_ok=True)
    sortie = ASSETS / "refus_document_non_cv.png"
    img.save(sortie, optimize=True)
    return sortie


# %% Lancement en ligne de commande
ETAPES = {
    "dataset": etape_1_dataset,
    "entrainer": etape_2_entrainer,
    "matrice": etape_3_matrice,
    "refus": etape_4_refus,
    "api": etape_5_api,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in (*ETAPES, "tout"):
        print(__doc__)
        raise SystemExit(1)
    etape, argument = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    if etape == "tout":
        etape_2_entrainer()
        etape_3_matrice()
        etape_4_refus(argument)
    elif etape in ("refus", "api"):
        ETAPES[etape](argument)
    else:
        ETAPES[etape]()
