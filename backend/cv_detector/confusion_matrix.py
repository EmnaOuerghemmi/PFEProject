"""
Détecteur de CV — figure « matrice de confusion » sur le jeu de test.

    cd backend
    python cv_detector/confusion_matrix.py

Rejoue le découpage de `train.py` (même graine, même stratification classe ×
langue) et évalue le modèle SAUVEGARDÉ, entraîné sur les 80 % d'entraînement
seulement : les 20 % de test n'ont jamais été vus. Aucun réentraînement.

Sortie : report/assets/matrice_confusion_detecteur_cv.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))

from app.services.cv_detection import DetecteurCV  # noqa: E402  (le vectoriseur référence son nettoyage)

GRAINE = 42
COLONNE = "texte_nettoye"
CLASSES = ["CV", "NOT_CV"]
LIBELLES = {"CV": "CV", "NOT_CV": "Non-CV"}
SORTIE = RACINE.parent.parent / "report" / "assets" / "matrice_confusion_detecteur_cv.png"
LOGO = RACINE.parent.parent / "frontend" / "public" / "logo.png"
FONTS = Path(r"C:\Windows\Fonts")


def evaluer() -> tuple[np.ndarray, dict[str, float]]:
    df = pd.read_csv(RACINE / "dataset.csv", encoding="utf-8-sig")
    strates = df["label"] + "_" + df["langue"]
    _, test = train_test_split(df, test_size=0.20, stratify=strates, random_state=GRAINE)

    modele = joblib.load(RACINE / "models" / DetecteurCV.FICHIER_MODELE)
    vectoriseur = joblib.load(RACINE / "models" / DetecteurCV.FICHIER_VECTORISEUR)
    proba_cv = modele.predict_proba(vectoriseur.transform(test[COLONNE]))[:, list(modele.classes_).index("CV")]
    y_predit = np.where(proba_cv >= 0.5, "CV", "NOT_CV")
    y_vrai = test["label"].to_numpy()

    matrice = confusion_matrix(y_vrai, y_predit, labels=CLASSES)
    metriques = {
        "Accuracy": accuracy_score(y_vrai, y_predit),
        "Précision": precision_score(y_vrai, y_predit, pos_label="CV", zero_division=0),
        "Rappel": recall_score(y_vrai, y_predit, pos_label="CV", zero_division=0),
        "F1": f1_score(y_vrai, y_predit, pos_label="CV", zero_division=0),
    }
    return matrice, metriques


# ── Dessin ───────────────────────────────────────────────────────────────────
S = 2
W, H = 1100, 980
INK, SOFT, MUTED = "#0F2440", "#1E3A5F", "#5B6B85"
BON, ERREUR = (35, 152, 90), (229, 72, 77)    # vert : bien classé, rouge : erreur


def _f(nom: str, taille: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / nom), int(taille * S))


def _melange(rgb: tuple[int, int, int], intensite: float) -> str:
    """Du blanc (intensité 0) à la couleur pleine (intensité 1)."""
    t = 0.12 + 0.88 * intensite
    return "#%02X%02X%02X" % tuple(int(255 + (c - 255) * t) for c in rgb)


def dessiner(matrice: np.ndarray, metriques: dict[str, float]) -> Path:
    img = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(img)
    P = lambda *v: [int(x * S) for x in v]                       # noqa: E731
    texte = lambda x, y, s, font, fill=INK, anchor="la": d.text(P(x, y), s, font=font, fill=fill, anchor=anchor)  # noqa: E731
    largeur = lambda s, font: d.textlength(s, font=font) / S     # noqa: E731

    # En-tête : logo + titre
    logo = Image.open(LOGO).convert("RGBA").resize((int(60 * S), int(60 * S)), Image.LANCZOS)
    t1, t2 = "PIQBIT", "Matrice de confusion du détecteur de CV"
    f1, f2 = _f("seguibl.ttf", 38), _f("seguisb.ttf", 30)
    total = 60 + 16 + largeur(t1, f1) + 30 + largeur(t2, f2)
    x = (W - total) / 2
    img.paste(logo, (int(x * S), int(26 * S)), logo)
    x += 76
    texte(x, 56, t1, f1, "#0B2A3C", "lm")
    x += largeur(t1, f1) + 15
    d.line(P(x, 32, x, 80), fill="#0B2A3C", width=int(3 * S))
    texte(x + 15, 56, t2, f2, "#123B6B", "lm")
    texte(W / 2, 108, "Jeu de test (20 %), seuil 0,5", _f("segoeui.ttf", 20), MUTED, "mm")

    # Grille 2 × 2
    cote, x0, y0 = 300, 330, 210
    lignes_tot = matrice.sum(axis=1)
    for i in range(2):
        for j in range(2):
            n = int(matrice[i, j])
            part = n / lignes_tot[i] if lignes_tot[i] else 0.0
            couleur = BON if i == j else ERREUR
            fond = _melange(couleur, part) if n else "#F5F7FA"
            cx0, cy0 = x0 + j * (cote + 14), y0 + i * (cote + 14)
            d.rounded_rectangle(P(cx0, cy0, cx0 + cote, cy0 + cote), radius=int(22 * S), fill=fond)
            encre = "white" if part > 0.5 else INK
            texte(cx0 + cote / 2, cy0 + cote / 2 - 18, str(n), _f("seguibl.ttf", 76), encre, "mm")
            texte(cx0 + cote / 2, cy0 + cote / 2 + 52, f"{part:.0%}".replace("%", " %"),
                  _f("seguisb.ttf", 24), encre, "mm")

    # Libellés des axes
    fl, fa = _f("segoeuib.ttf", 24), _f("seguisb.ttf", 20)
    for k, classe in enumerate(CLASSES):
        texte(x0 + k * (cote + 14) + cote / 2, y0 - 28, LIBELLES[classe], fl, SOFT, "mm")
        texte(x0 - 26, y0 + k * (cote + 14) + cote / 2, LIBELLES[classe], fl, SOFT, "rm")
    texte(x0 + cote + 7, y0 - 66, "Classe prédite", fa, MUTED, "mm")
    axe = Image.new("RGBA", (int(260 * S), int(40 * S)), (255, 255, 255, 0))
    ImageDraw.Draw(axe).text((axe.width // 2, axe.height // 2), "Classe réelle", font=fa, fill=MUTED, anchor="mm")
    axe = axe.rotate(90, expand=True)
    img.paste(axe, (int((x0 - 165) * S), int((y0 + cote + 7) * S - axe.height / 2)), axe)

    # Métriques
    fm, fv = _f("seguisb.ttf", 18), _f("seguibl.ttf", 30)
    largeur_carte, ecart = 190, 18
    xm = (W - (4 * largeur_carte + 3 * ecart)) / 2
    ym = y0 + 2 * cote + 14 + 48
    for nom, valeur in metriques.items():
        d.rounded_rectangle(P(xm, ym, xm + largeur_carte, ym + 92), radius=int(16 * S),
                            fill="#F5F8FC", outline="#DCE3EC", width=int(1.5 * S))
        texte(xm + largeur_carte / 2, ym + 28, nom.upper(), fm, MUTED, "mm")
        texte(xm + largeur_carte / 2, ym + 62, f"{valeur:.2f}".replace(".", ","), fv, INK, "mm")
        xm += largeur_carte + ecart

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    img.save(SORTIE, optimize=True)
    return SORTIE


def main() -> None:
    matrice, metriques = evaluer()
    print(f"{'':12}{'prédit CV':>12}{'prédit Non-CV':>16}")
    for i, classe in enumerate(CLASSES):
        print(f"{'réel ' + LIBELLES[classe]:12}{matrice[i][0]:>12}{matrice[i][1]:>16}")
    print("  ".join(f"{k} {v:.4f}" for k, v in metriques.items()))
    print(dessiner(matrice, metriques))


if __name__ == "__main__":
    main()
