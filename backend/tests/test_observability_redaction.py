"""
Tests du masquage avant envoi au traceur externe.

Ces tests existent pour une raison précise : le pipeline tracé manipule des CV,
et la règle du projet interdit d'en faire sortir les données personnelles. Un
traceur est un journal. Si ces tests tombent, une fuite est possible — ils ne
sont pas décoratifs.

Le test central est `test_aucune_fuite_sur_un_cv_realiste` : il prend un CV
contenant nom, téléphone, adresse et employeur, le passe par chaque fonction de
masquage, et vérifie qu'AUCUN de ces fragments ne se retrouve dans la sortie.
"""
import pytest

from app.core.config import settings
from app.observability.redaction import (
    MASK_FLAG,
    SEUIL_TEXTE_LIBRE,
    empreinte,
    filet_de_securite,
    masquer_identifiant,
    masquer_passages,
    masquer_texte,
    metadonnees_sures,
)


@pytest.fixture
def contenu_masque(monkeypatch):
    """Comportement par défaut : le contenu ne sort pas."""
    monkeypatch.setattr(settings, "LANGFUSE_TRACE_CONTENT", False)


@pytest.fixture
def contenu_autorise(monkeypatch):
    """Traçage du contenu explicitement activé (instance auto-hébergée)."""
    monkeypatch.setattr(settings, "LANGFUSE_TRACE_CONTENT", True)
    monkeypatch.setattr(settings, "LANGFUSE_CONTENT_MAX_CHARS", 50)


CV_REALISTE = (
    "Emna Ouerghemmi, née le 12/03/1999 à Tunis. "
    "Téléphone : +216 98 123 456. Courriel : emna.test@example.com. "
    "Adresse : 14 rue de Carthage, La Marsa. "
    "Ingénieure logiciel chez Novyra Software depuis 2023. "
    "Compétences : Python, Angular, PostgreSQL, FastAPI."
)

FRAGMENTS_SENSIBLES = [
    "Ouerghemmi", "98 123 456", "emna.test@example.com",
    "rue de Carthage", "Novyra", "12/03/1999",
]


# ── Comportement par défaut : rien ne sort ──────────────────────────────────

def test_texte_masque_par_defaut(contenu_masque):
    sortie = masquer_texte(CV_REALISTE, etiquette="cv")
    assert sortie[MASK_FLAG] is True
    assert "content" not in sortie
    assert sortie["chars"] == len(CV_REALISTE)
    assert sortie["kind"] == "cv"


def test_aucune_fuite_sur_un_cv_realiste(contenu_masque):
    """Le test qui compte : aucun fragment identifiant ne doit apparaître."""
    sorties = [
        str(masquer_texte(CV_REALISTE)),
        str(masquer_passages(CV_REALISTE.split(". "))),
        str(masquer_identifiant("3f2504e0-4f89-11d3-9a0c-0305e82c3301")),
        str(metadonnees_sures(question=CV_REALISTE, score=0.9, count=3)),
    ]
    rendu = " ".join(sorties)
    for fragment in FRAGMENTS_SENSIBLES:
        assert fragment not in rendu, f"fuite de « {fragment} » dans la trace"


def test_passages_masques_gardent_les_longueurs(contenu_masque):
    """
    Les longueurs restent visibles : une récupération qui ne ramène que des
    passages minuscules signale un découpage défaillant, et ce diagnostic ne
    demande pas de lire les passages.
    """
    passages = ["abc" * 10, "x" * 200, "y" * 5]
    sortie = masquer_passages(passages)
    assert sortie[MASK_FLAG] is True
    assert "content" not in sortie
    assert sortie["count"] == 3
    assert sortie["chars_each"] == [30, 200, 5]
    assert sortie["chars_total"] == 235


def test_metadonnees_laissent_passer_les_nombres(contenu_masque):
    sortie = metadonnees_sures(score=0.87, count=4, actif=True, rien=None)
    assert sortie == {"score": 0.87, "count": 4, "actif": True, "rien": None}


def test_metadonnees_laissent_passer_le_vocabulaire_technique(contenu_masque):
    sortie = metadonnees_sures(cache="hit", mode="native")
    assert sortie == {"cache": "hit", "mode": "native"}


def test_metadonnees_masquent_toute_chaine_inconnue(contenu_masque):
    """
    Le point important : un champ ajouté par mégarde est masqué PAR DÉFAUT.
    Une liste blanche qui laisserait passer l'inconnu ne protégerait rien.
    """
    sortie = metadonnees_sures(commentaire="Le candidat a travaillé chez Novyra")
    assert sortie["commentaire"][MASK_FLAG] is True
    assert "Novyra" not in str(sortie)


def test_liste_de_nombres_acceptee(contenu_masque):
    sortie = metadonnees_sures(top_scores=[0.91, 0.42, 0.13])
    assert sortie["top_scores"] == [0.91, 0.42, 0.13]


# ── Empreintes : corréler sans révéler ──────────────────────────────────────

def test_empreinte_stable_et_discriminante():
    assert empreinte("même question") == empreinte("même question")
    assert empreinte("question A") != empreinte("question B")
    assert len(empreinte("x")) == 12


def test_empreinte_ne_contient_pas_la_source():
    assert "Ouerghemmi" not in empreinte(CV_REALISTE)


def test_identifiant_masque_reste_correlable():
    uid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    assert masquer_identifiant(uid) == masquer_identifiant(uid)
    assert uid not in str(masquer_identifiant(uid))
    assert masquer_identifiant(None) is None


# ── Traçage du contenu explicitement autorisé ───────────────────────────────

def test_contenu_sort_quand_explicitement_autorise(contenu_autorise):
    sortie = masquer_texte(CV_REALISTE)
    assert MASK_FLAG not in sortie
    assert sortie["content"] == CV_REALISTE[:50]
    assert sortie["truncated"] is True


def test_contenu_court_non_marque_tronque(contenu_autorise):
    sortie = masquer_texte("court")
    assert sortie["content"] == "court"
    assert sortie["truncated"] is False


# ── Filet de sécurité branché sur le SDK ────────────────────────────────────
#
# Seconde ligne de défense : les sites d'appel masquent déjà, mais c'est une
# discipline. Ce filet s'applique à TOUT ce que le SDK envoie et ne dépend
# d'aucune vigilance — il rattrape un champ ajouté par mégarde.

def test_filet_masque_un_cv_glisse_dans_les_metadonnees(contenu_masque):
    """Le scénario que ce filet existe pour rattraper."""
    charge = {"metadata": {"cv_brut": CV_REALISTE}, "score": 0.9}
    sortie = filet_de_securite(data=charge)
    rendu = str(sortie)
    for fragment in FRAGMENTS_SENSIBLES:
        assert fragment not in rendu, f"fuite de « {fragment} » malgré le filet"
    assert sortie["score"] == 0.9


def test_filet_laisse_passer_les_libelles_techniques(contenu_masque):
    """Un filet qui masquerait tout rendrait les traces inutiles."""
    charge = {"outcome": "ok", "cache": "hit", "model": "sentence-transformers",
              "count": 12, "scores": [0.9, 0.4]}
    assert filet_de_securite(data=charge) == charge


def test_filet_masque_au_dela_du_seuil(contenu_masque):
    court = "x" * (SEUIL_TEXTE_LIBRE - 1)
    long = "y" * (SEUIL_TEXTE_LIBRE + 1)
    sortie = filet_de_securite(data={"court": court, "long": long})
    assert sortie["court"] == court
    assert sortie["long"][MASK_FLAG] is True


def test_filet_descend_dans_les_structures_imbriquees(contenu_masque):
    charge = {"a": {"b": {"c": [{"d": CV_REALISTE}]}}}
    rendu = str(filet_de_securite(data=charge))
    assert "Ouerghemmi" not in rendu


def test_filet_preserve_un_descripteur_deja_masque(contenu_masque):
    """
    Remasquer un descripteur écraserait longueurs et empreintes — c'est-à-dire
    précisément l'information que le masquage avait pris soin de conserver.
    """
    deja = masquer_texte(CV_REALISTE, etiquette="cv")
    sortie = filet_de_securite(data={"question": deja})
    assert sortie["question"]["chars"] == len(CV_REALISTE)
    assert sortie["question"]["sha256_12"] == empreinte(CV_REALISTE)


def test_filet_inactif_quand_le_contenu_est_autorise(contenu_autorise):
    charge = {"cv": CV_REALISTE}
    assert filet_de_securite(data=charge) == charge


def test_filet_borne_la_profondeur(contenu_masque):
    """Une structure cyclique ou très profonde ne doit pas faire boucler."""
    charge: dict = {"n": 0}
    courant = charge
    for i in range(1, 30):
        courant["suivant"] = {"n": i}
        courant = courant["suivant"]
    sortie = filet_de_securite(data=charge)
    assert sortie is not None
