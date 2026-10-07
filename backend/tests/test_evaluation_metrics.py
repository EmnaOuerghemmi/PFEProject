"""
Tests des métriques d'évaluation.

Ces métriques jugent la qualité du moteur : si elles sont fausses, tout
jugement porté sur le moteur l'est aussi. Elles se testent donc sur des cas
dont la valeur attendue se calcule à la main.

Le module `evaluation.metrics` n'a aucune dépendance : ces tests s'exécutent
partout, sans base de données ni modèle.
"""
import pytest

from evaluation.metrics import (
    Rapport,
    ResultatCas,
    ancrage_exact,
    correspond,
    couverture_mots_cles,
    normaliser,
    precision_a_k,
    precision_moyenne,
    rang_reciproque,
    rappel_a_k,
    taux_de_succes,
)

P1 = "Le candidat maîtrise Python et Angular."
P2 = "Diplôme national d'ingénieur en génie logiciel, obtenu en 2021."
P3 = "Arabe langue maternelle, français courant."


# ── Normalisation ───────────────────────────────────────────────────────────

def test_normalisation_retire_accents_et_casse():
    assert normaliser("Expérience") == normaliser("EXPERIENCE")
    assert normaliser("Diplôme d'ingénieur !") == "diplome d ingenieur"


def test_normalisation_tolere_le_vide():
    assert normaliser("") == ""
    assert normaliser(None) == ""


# ── Correspondance de passages ──────────────────────────────────────────────

def test_correspondance_identique():
    assert correspond(P1, P1) is True


def test_correspondance_sur_passage_englobant():
    """
    Un passage récupéré plus long qui CONTIENT l'attendu doit compter comme
    une réussite : c'est un découpage différent, pas une erreur.
    """
    englobant = "Compétences. " + P1 + " Il connaît aussi Docker."
    assert correspond(englobant, P1) is True


def test_correspondance_refusee_sur_passage_different():
    assert correspond(P3, P1) is False


def test_correspondance_insensible_aux_accents():
    assert correspond("le candidat maitrise python et angular", P1) is True


# ── Métriques de récupération, valeurs calculées à la main ──────────────────

def test_taux_de_succes():
    assert taux_de_succes([P1, P2, P3], [P2], k=3) == 1.0
    assert taux_de_succes([P1, P3], [P2], k=3) == 0.0
    # P2 est au rang 3 : hors des 2 premiers.
    assert taux_de_succes([P1, P3, P2], [P2], k=2) == 0.0


def test_taux_de_succes_sans_verite_terrain():
    assert taux_de_succes([P1], [], k=3) == 0.0


def test_rang_reciproque_distingue_le_rang():
    assert rang_reciproque([P2, P1, P3], [P2]) == 1.0
    assert rang_reciproque([P1, P2, P3], [P2]) == 0.5
    assert rang_reciproque([P1, P3, P2], [P2]) == pytest.approx(1 / 3)
    assert rang_reciproque([P1, P3], [P2]) == 0.0


def test_precision_a_k():
    # 1 pertinent sur 3 récupérés.
    assert precision_a_k([P1, P2, P3], [P2], k=3) == pytest.approx(1 / 3)
    # 2 pertinents sur 3.
    assert precision_a_k([P1, P2, P3], [P1, P2], k=3) == pytest.approx(2 / 3)


def test_rappel_a_k():
    # 1 attendu sur 2 retrouvé.
    assert rappel_a_k([P1, P3], [P1, P2], k=3) == 0.5
    assert rappel_a_k([P1, P2], [P1, P2], k=3) == 1.0
    assert rappel_a_k([P3], [P1], k=3) == 0.0


def test_precision_moyenne_recompense_le_groupement():
    """Deux pertinents en tête valent mieux que deux pertinents dispersés."""
    groupes = precision_moyenne([P1, P2, P3], [P1, P2])
    disperses = precision_moyenne([P1, P3, P2], [P1, P2])
    assert groupes > disperses
    assert groupes == 1.0  # rangs 1 et 2 : (1/1 + 2/2) / 2


# ── Métriques de réponse ────────────────────────────────────────────────────

def test_couverture_mots_cles():
    assert couverture_mots_cles(P1, ["Python", "Angular"]) == 1.0
    assert couverture_mots_cles(P1, ["Python", "Docker"]) == 0.5
    assert couverture_mots_cles(P1, ["Docker"]) == 0.0


def test_couverture_insensible_aux_accents():
    assert couverture_mots_cles("Diplôme d'ingénieur", ["ingenieur"]) == 1.0


def test_couverture_sans_mots_cles():
    assert couverture_mots_cles(P1, []) == 0.0


# ── Ancrage : le point délicat ──────────────────────────────────────────────

def test_ancrage_vaut_un_quand_la_reponse_vient_du_contexte():
    assert ancrage_exact(P1, [P1, P2]) == 1.0


def test_ancrage_vaut_zero_sur_une_reponse_inventee():
    """Le cas que la métrique existe pour détecter : une réponse hors contexte."""
    assert ancrage_exact("Le candidat parle japonais.", [P1, P2]) == 0.0


def test_ancrage_sans_objet_sur_un_refus():
    """
    Distinction essentielle : une absence de réponse n'est PAS une réponse
    infidèle. Renvoyer 0,0 ici ferait chuter la moyenne à chaque question
    légitimement sans réponse, et déclencherait une fausse alerte.
    """
    assert ancrage_exact("", [P1]) is None
    assert ancrage_exact("   ", [P1]) is None


def test_ancrage_accepte_un_extrait_partiel():
    assert ancrage_exact("maîtrise Python", [P1]) == 1.0


# ── Agrégation ──────────────────────────────────────────────────────────────

def _cas(identifiant: str, succes: float, ancrage) -> ResultatCas:
    return ResultatCas(
        identifiant=identifiant, question="q", taux_succes=succes,
        rang_reciproque=succes, precision=succes, rappel=succes,
        precision_moyenne=succes, couverture=succes, ancrage=ancrage,
        confiance=0.5, passages_recuperes=1,
    )


def test_moyenne_exclut_les_ancrages_sans_objet():
    """
    Deux cas ancrés à 1,0 et deux refus : la moyenne doit valoir 1,0 sur
    2 cas, et non 0,5 sur 4.
    """
    r = Rapport(k=3)
    r.ajouter(_cas("a", 1.0, 1.0))
    r.ajouter(_cas("b", 1.0, 1.0))
    r.ajouter(_cas("c", 1.0, None))
    r.ajouter(_cas("d", 1.0, None))
    synthese = r.synthese()
    assert synthese["groundedness"] == 1.0
    assert synthese["groundedness_applicable_cases"] == 2


def test_synthese_sur_rapport_vide():
    synthese = Rapport(k=3).synthese()
    assert synthese["cases"] == 0
    assert synthese["hit_rate"] == 0.0


def test_echecs_listent_les_cas_sous_le_seuil():
    r = Rapport(k=3)
    r.ajouter(_cas("bon", 1.0, 1.0))
    r.ajouter(_cas("mauvais", 0.0, 0.0))
    echecs = r.echecs()
    assert [c.identifiant for c in echecs] == ["mauvais"]


def test_en_dict_serialise_un_ancrage_absent():
    d = _cas("x", 1.0, None).en_dict()
    assert d["groundedness"] is None
