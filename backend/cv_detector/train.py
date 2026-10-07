"""
Détecteur de CV — entraînement : TF-IDF + régression logistique.

    cd backend
    python cv_detector/train.py

Étapes, dans l'ordre :

  1-3. Reconstruit dataset.csv (extraction + nettoyage, `build_dataset.py`).
  4.   Découpage 80 % entraînement / 20 % test, stratifié par classe ET langue.
  5.   TF-IDF : texte -> vecteur numérique, appris sur les documents ORIGINAUX
       de l'entraînement. Le nettoyage est le `preprocessor` du vectoriseur :
       il voyage avec lui dans le fichier sauvegardé.
  6.   Régression logistique : model.fit(X_train, y_train), sur les originaux
       ET des extraits courts des CV (aucun CV collecté n'est court, et le
       modèle apprenait « court = pas un CV »), chaque groupe classe x langue
       pondéré à égalité (60 des 70 documents français sont des non-CV : sans
       cela, « français » finit par vouloir dire « pas un CV »).
       Le seul hyperparamètre (C) est choisi par validation croisée sur
       l'ENTRAÎNEMENT uniquement — le test n'est jamais regardé avant
       l'évaluation — et sur la perte logarithmique, parce que l'API décide sur
       la VALEUR de la probabilité, pas seulement sur la classe prédite.
  7.   Évaluation sur le test : accuracy, precision, recall, F1, matrice de
       confusion — puis validation croisée 5 plis sur tout le dataset, parce
       qu'un test de 34 documents dont 10 CV donne des chiffres qui bougent de
       10 points à la moindre erreur.
  8.   Tests de résistance aux biais du dataset (format, longueur).
  9.   Sauvegarde : models/cv_classifier.joblib + models/tfidf_vectorizer.joblib
       + models/metadata.json.

Les documents ne sont désignés que par leur identifiant anonyme (CV_EN_007) ;
dataset.csv relie chaque identifiant à son fichier.
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, log_loss, precision_score, recall_score)
from sklearn.model_selection import StratifiedKFold, train_test_split

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE.parent))

from app.core.config import settings  # noqa: E402
from app.services.cv_detection import DetecteurCV, nettoyer_texte  # noqa: E402
from app.services.cv_parser import cv_parser  # noqa: E402
from build_dataset import construire  # noqa: E402

DOSSIER_MODELES = RACINE / "models"
GRAINE = 42
# Texte nettoyé, artefacts de collecte retirés (cf. build_dataset.py).
COLONNE = "texte_nettoye"
CLASSES = ["CV", "NOT_CV"]
VALEURS_C = [0.1, 1.0, 10.0, 100.0, 1000.0]
EXTRAITS_PAR_CV = 4
MOTS_PAR_EXTRAIT = (80, 180)
SEUIL_ACCEPTE = settings.CV_DETECTOR_ACCEPT_THRESHOLD
SEUIL_REFUS = settings.CV_DETECTOR_REJECT_THRESHOLD


def _titre(texte: str) -> None:
    print(f"\n{'═' * 78}\n {texte}\n{'═' * 78}")


# ── Modèle ────────────────────────────────────────────────────────────────────

def _vectoriseur() -> TfidfVectorizer:
    return TfidfVectorizer(
        preprocessor=nettoyer_texte,   # le nettoyage fait partie du modèle
        ngram_range=(1, 2),            # « professional experience », « relevé de notes »
        min_df=2,                      # vu dans un seul document : bruit, ou nom propre
        max_df=0.95,
        sublinear_tf=True,             # 20 occurrences ne valent pas 20 fois une
    )


def _poids_strates(part: pd.DataFrame) -> np.ndarray:
    """
    Poids d'échantillon : chaque groupe classe × langue pèse autant au total.

    60 des 70 documents français sont des non-CV. Sans correction, le modèle
    apprend « texte en français -> pas un CV » — mesuré : un CV français sur
    dix tombait à 0,35 et aurait été refusé. Pondérer corrige ce déséquilibre
    sans retirer un seul mot du texte.
    """
    strate = part["label"] + "_" + part["langue"]
    effectifs = strate.map(strate.value_counts())
    return (len(part) / (strate.nunique() * effectifs)).to_numpy()


def _augmenter(part: pd.DataFrame, graine: int) -> pd.DataFrame:
    """
    Ajoute, pour chaque CV, des extraits contigus de 80 à 180 mots — la longueur
    d'un CV d'une page sobre.

    Aucun CV du dataset ne fait moins de 1 131 caractères, alors que tous les
    documents courts sont des non-CV : le modèle apprenait « court = pas un CV ».
    Mesuré : un CV fictif d'une page, parfaitement construit, était refusé
    (probabilité 0,21), et 9 CV sur 46 tronqués à 800 caractères basculaient.

    À n'appliquer qu'à des données d'ENTRAÎNEMENT.
    """
    generateur = np.random.default_rng(graine)
    extraits = []
    for cv in part[part["label"] == "CV"].itertuples():
        mots = getattr(cv, COLONNE).split()
        for _ in range(EXTRAITS_PAR_CV):
            taille = int(generateur.integers(MOTS_PAR_EXTRAIT[0], MOTS_PAR_EXTRAIT[1], endpoint=True))
            debut = int(generateur.integers(0, max(1, len(mots) - taille)))
            extraits.append({"label": "CV", "langue": cv.langue,
                             COLONNE: " ".join(mots[debut:debut + taille])})
    return pd.concat([part, pd.DataFrame(extraits)], ignore_index=True)


def _entrainer(originaux: pd.DataFrame, c: float, graine: int
               ) -> tuple[TfidfVectorizer, LogisticRegression]:
    """
    model.fit(X_train, y_train), en deux temps volontairement séparés.

    1. Le vectoriseur — vocabulaire et poids IDF — est appris sur les documents
       ORIGINAUX seuls. Un extrait reprend les termes de son CV : compté comme
       un document de plus, il ferait passer le filtre `min_df=2` aux termes
       vus dans un seul CV — nom, ville, école d'un candidat — qui seraient
       alors enregistrés dans le vocabulaire sauvegardé. Mesuré : le
       vocabulaire triplait (5 794 -> 15 509 termes).
    2. La régression est entraînée sur les originaux ET leurs extraits.
    """
    vectoriseur = _vectoriseur().fit(originaux[COLONNE])
    augmente = _augmenter(originaux, graine)
    modele = LogisticRegression(C=c, max_iter=5000)
    modele.fit(vectoriseur.transform(augmente[COLONNE]), augmente["label"],
               sample_weight=_poids_strates(augmente))
    return vectoriseur, modele


def _proba_cv(vectoriseur: TfidfVectorizer, modele: LogisticRegression, textes) -> np.ndarray:
    return modele.predict_proba(vectoriseur.transform(textes))[:, list(modele.classes_).index("CV")]


def _hors_pli(originaux: pd.DataFrame, c: float) -> np.ndarray:
    """Probabilité CV de chaque document, prédite par un modèle entraîné SANS lui (5 plis)."""
    proba = np.zeros(len(originaux))
    plis = StratifiedKFold(5, shuffle=True, random_state=GRAINE)
    for rang, (i_entr, i_eval) in enumerate(plis.split(originaux[COLONNE], originaux["label"])):
        vectoriseur, modele = _entrainer(originaux.iloc[i_entr], c, GRAINE + rang)
        proba[i_eval] = _proba_cv(vectoriseur, modele, originaux[COLONNE].iloc[i_eval])
    return proba


# ── Rapports ──────────────────────────────────────────────────────────────────

def _matrice(y_vrai, y_predit) -> None:
    m = confusion_matrix(y_vrai, y_predit, labels=CLASSES)
    print(f"\n{'':16}{'prédit CV':>12}{'prédit NOT_CV':>15}")
    for i, classe in enumerate(CLASSES):
        print(f"{'réel ' + classe:16}{m[i][0]:>12}{m[i][1]:>15}")


def _zones(probas: np.ndarray, etiquettes: pd.Series) -> dict:
    """Répartition dans les trois zones de décision de l'API."""
    zones = {}
    for classe in CLASSES:
        p = probas[(etiquettes == classe).to_numpy()]
        zones[classe] = {
            "accepte": int((p >= SEUIL_ACCEPTE).sum()),
            "incertain": int(((p >= SEUIL_REFUS) & (p < SEUIL_ACCEPTE)).sum()),
            "refuse": int((p < SEUIL_REFUS).sum()),
            "total": int(len(p)),
        }
    return zones


def _en_pdf(texte: str) -> bytes:
    """Rend un texte en PDF, pour le relire ensuite comme un dépôt réel."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate
    tampon = BytesIO()
    style = getSampleStyleSheet()["Normal"]
    blocs = [Paragraph(escape(l), style) for l in texte.splitlines() if l.strip()]
    SimpleDocTemplate(tampon, pagesize=A4).build(blocs or [Paragraph(" ", style)])
    return tampon.getvalue()


def main() -> None:
    # ── 1-3. Dataset ─────────────────────────────────────────────────────────
    _titre("1-3. EXTRACTION, DATASET.CSV, NETTOYAGE")
    construire(verbeux=True)
    df = pd.read_csv(RACINE / "dataset.csv", encoding="utf-8-sig")

    # ── 4. Découpage ─────────────────────────────────────────────────────────
    _titre("4. DÉCOUPAGE 80 % / 20 %")
    strates = df["label"] + "_" + df["langue"]
    entr, test = train_test_split(df, test_size=0.20, stratify=strates, random_state=GRAINE)
    entr, test = entr.reset_index(drop=True), test.reset_index(drop=True)
    for nom, part in (("entraînement", entr), ("test", test)):
        detail = ", ".join(f"{k} {v}" for k, v in (part["label"] + "_" + part["langue"]).value_counts().sort_index().items())
        print(f"{nom:13} {len(part):>4} documents   ({detail})")

    # ── 5-6. TF-IDF + régression logistique ──────────────────────────────────
    _titre("5-6. TF-IDF + RÉGRESSION LOGISTIQUE")
    print(f"Chaque CV d'entraînement reçoit {EXTRAITS_PAR_CV} extraits de "
          f"{MOTS_PAR_EXTRAIT[0]} à {MOTS_PAR_EXTRAIT[1]} mots (jamais le test).")
    print("Choix de C — validation croisée 5 plis sur l'entraînement uniquement :")
    y_entr = (entr["label"] == "CV").astype(int)
    resultats = {}
    for c in VALEURS_C:
        p = _hors_pli(entr, c)
        resultats[c] = (log_loss(y_entr, p),
                        f1_score(entr["label"], np.where(p >= 0.5, "CV", "NOT_CV"), average="macro"))
    meilleur_c = min(resultats, key=lambda c: resultats[c][0])
    for c, (perte, f1) in resultats.items():
        print(f"  C = {c:<7} perte logarithmique {perte:.3f}   F1 macro {f1:.3f}"
              + ("   <- retenu" if c == meilleur_c else ""))

    vectoriseur, modele = _entrainer(entr, meilleur_c, GRAINE)     # model.fit(X_train, y_train)
    print(f"\nVocabulaire TF-IDF : {len(vectoriseur.vocabulary_)} termes (mots et paires de mots), "
          f"appris sur les {len(entr)} documents originaux")
    exemple = nettoyer_texte("Professional Experience — Skills: Python, SQL")
    vec = vectoriseur.transform([exemple]).toarray()[0]
    print(f"Exemple : « {exemple} »\n      -> vecteur de {len(vec)} nombres, dont "
          f"{int((vec > 0).sum())} non nuls : {np.round(vec[vec > 0][:6], 2).tolist()} …")

    # ── 7. Évaluation ────────────────────────────────────────────────────────
    _titre("7. ÉVALUATION SUR LE JEU DE TEST (jamais vu à l'entraînement)")
    proba_test = _proba_cv(vectoriseur, modele, test[COLONNE])
    y_predit = np.where(proba_test >= 0.5, "CV", "NOT_CV")
    print(f"Accuracy : {accuracy_score(test['label'], y_predit):.3f}\n")
    print(classification_report(test["label"], y_predit, labels=CLASSES, digits=2))
    _matrice(test["label"], y_predit)
    erreurs = (test["label"] != y_predit).to_numpy()
    if erreurs.any():
        print("\nDocuments mal classés :")
        for ligne, p in zip(test[erreurs].itertuples(), proba_test[erreurs]):
            print(f"  {ligne.id:12} {ligne.categorie:22} probabilité CV {p:.2f}")
    else:
        print("\nAucun document du test mal classé.")

    _titre("7 bis. VALIDATION CROISÉE 5 PLIS SUR TOUS LES DOCUMENTS")
    print("Chaque document est prédit une fois, par un modèle entraîné sans lui")
    print("(chaque pli reçoit ses propres extraits ; les documents évalués sont les originaux).")
    proba_oof = _hors_pli(df, meilleur_c)
    y_oof = np.where(proba_oof >= 0.5, "CV", "NOT_CV")
    plis = StratifiedKFold(5, shuffle=True, random_state=GRAINE)
    f1_plis = [f1_score(df["label"].iloc[i], y_oof[i], pos_label="CV")
               for _, i in plis.split(df[COLONNE], df["label"])]
    print(f"Accuracy {accuracy_score(df['label'], y_oof):.3f} | F1 (CV) "
          f"{statistics.mean(f1_plis):.3f} ± {statistics.pstdev(f1_plis):.3f} selon le pli")
    _matrice(df["label"], y_oof)

    zones = _zones(proba_oof, df["label"])
    print(f"\nZones de décision de l'API (seuils {SEUIL_REFUS:.2f} / {SEUIL_ACCEPTE:.2f}), "
          f"sur les {len(df)} prédictions hors-pli :")
    print(f"{'':10}{'accepté':>10}{'incertain':>11}{'refusé':>9}")
    for classe in CLASSES:
        z = zones[classe]
        print(f"{classe:10}{z['accepte']:>10}{z['incertain']:>11}{z['refuse']:>9}")
    for langue, nom in (("en", "anglais"), ("fr", "français")):
        p_cv = proba_oof[((df["label"] == "CV") & (df["langue"] == langue)).to_numpy()]
        print(f"  CV en {nom:9}: probabilité médiane {np.median(p_cv):.2f}, minimum {p_cv.min():.2f}, "
              f"sous {SEUIL_ACCEPTE:.2f} : {int((p_cv < SEUIL_ACCEPTE).sum())} / {len(p_cv)}")
    print(f"  -> vrais CV refusés à tort : {zones['CV']['refuse']} / {zones['CV']['total']}"
          f"   |   non-CV laissés passer : {zones['NOT_CV']['accepte'] + zones['NOT_CV']['incertain']}"
          f" / {zones['NOT_CV']['total']}")

    _titre("7 ter. CE QUE LE MODÈLE A APPRIS — termes les plus déterminants")
    termes = np.array(vectoriseur.get_feature_names_out())
    # Régression binaire : un coefficient positif pousse vers classes_[1] (NOT_CV).
    poids = modele.coef_[0] if modele.classes_[1] == "NOT_CV" else -modele.coef_[0]
    ordre = np.argsort(poids)
    print("vers CV     : " + ", ".join(f"{termes[i]} ({-poids[i]:.2f})" for i in ordre[:15]))
    print("vers NOT_CV : " + ", ".join(f"{termes[i]} ({poids[i]:.2f})" for i in ordre[::-1][:15]))

    # ── 8. Tests de résistance ───────────────────────────────────────────────
    _titre("8. TESTS DE RÉSISTANCE AUX BIAIS DU DATASET (documents du test, transformés)")
    non_cv_test = test[test["label"] == "NOT_CV"]
    cv_test = test[test["label"] == "CV"]

    # a. Format : tous les CV sont des PDF/DOCX, tous les non-CV des .txt.
    textes_pdf = [cv_parser.extract_text_from_bytes(_en_pdf(t), ".pdf") for t in non_cv_test[COLONNE]]
    p_format = _proba_cv(vectoriseur, modele, textes_pdf)
    print(f"a. Format   — {len(textes_pdf)} non-CV du test mis en PDF puis relus comme un dépôt :")
    print(f"             classés CV à tort : {int((p_format >= 0.5).sum())}   "
          f"(probabilité CV médiane {np.median(p_format):.2f})")

    # b. Longueur, sens 1 : un non-CV aussi long qu'un CV.
    longs = [" \n".join(groupe[COLONNE]) for _, groupe in non_cv_test.groupby("categorie")]
    p_longs = _proba_cv(vectoriseur, modele, longs)
    print(f"b. Longueur — {len(longs)} non-CV longs (documents du test d'une même catégorie mis bout à bout, "
          f"médiane {statistics.median(len(t) for t in longs):.0f} caractères) :")
    print(f"             classés CV à tort : {int((p_longs >= 0.5).sum())}   "
          f"(probabilités CV : {', '.join(f'{p:.2f}' for p in p_longs)})")

    # c. Longueur, sens 2 : un CV aussi court qu'un non-CV.
    courts = [t[:800] for t in cv_test[COLONNE]]
    p_courts = _proba_cv(vectoriseur, modele, courts)
    print(f"c. Longueur — {len(courts)} CV du test tronqués à 800 caractères (longueur d'un non-CV) :")
    print(f"             encore reconnus comme CV : {int((p_courts >= 0.5).sum())} / {len(courts)}   "
          f"(probabilité CV médiane {np.median(p_courts):.2f})")

    # ── 9. Sauvegarde ────────────────────────────────────────────────────────
    _titre("9. SAUVEGARDE")
    # `stop_words_` liste les termes écartés par min_df/max_df : avec min_df=2,
    # ce sont les mots vus dans UN seul document — noms, villes, écoles des
    # candidats. Inutile à la prédiction ; à ne pas enregistrer.
    if getattr(vectoriseur, "stop_words_", None) is not None:
        vectoriseur.stop_words_ = None
    DOSSIER_MODELES.mkdir(exist_ok=True)
    joblib.dump(modele, DOSSIER_MODELES / DetecteurCV.FICHIER_MODELE, compress=3)
    joblib.dump(vectoriseur, DOSSIER_MODELES / DetecteurCV.FICHIER_VECTORISEUR, compress=3)
    metadonnees = {
        "format": "cv_detector_v1",
        "algorithme": "TF-IDF (mots et paires de mots) + régression logistique",
        "entraine_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scikit_learn": sklearn.__version__,
        "documents": {"total": int(len(df)), "entrainement": int(len(entr)), "test": int(len(test)),
                      "cv": int((df["label"] == "CV").sum()), "non_cv": int((df["label"] == "NOT_CV").sum())},
        "hyperparametres": {"C": meilleur_c, "ngram_range": [1, 2], "min_df": 2, "max_df": 0.95,
                            "sublinear_tf": True, "ponderation": "classe x langue"},
        "augmentation": {"extraits_par_cv": EXTRAITS_PAR_CV, "mots_par_extrait": list(MOTS_PAR_EXTRAIT),
                         "vocabulaire_appris_sur": "documents originaux seulement"},
        "vocabulaire": int(len(vectoriseur.vocabulary_)),
        "test": {
            "accuracy": round(accuracy_score(test["label"], y_predit), 4),
            "precision_cv": round(precision_score(test["label"], y_predit, pos_label="CV"), 4),
            "recall_cv": round(recall_score(test["label"], y_predit, pos_label="CV"), 4),
            "f1_cv": round(f1_score(test["label"], y_predit, pos_label="CV"), 4),
        },
        "validation_croisee_5_plis": {"f1_cv_moyen": round(statistics.mean(f1_plis), 4),
                                      "f1_cv_ecart_type": round(statistics.pstdev(f1_plis), 4)},
        "seuils": {"accepte": SEUIL_ACCEPTE, "refuse": SEUIL_REFUS},
        "zones_hors_pli": zones,
    }
    (DOSSIER_MODELES / DetecteurCV.FICHIER_METADONNEES).write_text(
        json.dumps(metadonnees, ensure_ascii=False, indent=2), encoding="utf-8")
    for fichier in sorted(DOSSIER_MODELES.iterdir()):
        print(f"  {fichier.relative_to(RACINE.parent).as_posix():45} {fichier.stat().st_size / 1024:>8.1f} Ko")


if __name__ == "__main__":
    main()
