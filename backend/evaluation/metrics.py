"""
Métriques de qualité de récupération — **sans aucune dépendance externe**.

Ce module est volontairement autonome : il n'importe ni Ragas, ni langchain, ni
le reste de l'application. Il tourne avec la bibliothèque standard. C'est ce
qui garantit qu'une évaluation reste possible même quand l'arbre de
dépendances de Ragas refuse de s'installer — ce qui arrive.

DEUX FAMILLES DE MESURES.

1. **Récupération.** Les passages retenus sont-ils les bons ? Ce sont les
   métriques classiques de recherche d'information : taux de succès, rang
   réciproque moyen, précision et rappel à k. Elles répondent à la seule
   question qui compte pour un moteur extractif — a-t-on ramené le bon extrait
   du CV ?

2. **Réponse.** L'extrait rendu contient-il l'information attendue ?
   Mesurée par couverture de mots-clés, et par une vérification d'ancrage.

UN MOT SUR L'ANCRAGE (« faithfulness »). Ragas mesure la fidélité d'une réponse
à son contexte au moyen d'un modèle de langage juge, parce qu'une réponse
générée reformule et qu'aucune comparaison littérale n'est possible. Ici, le
moteur est extractif : la réponse EST un passage du contexte. L'ancrage se
vérifie donc **exactement**, par appartenance de chaîne — ce qui est plus sûr,
plus rapide et gratuit. `ancrage_exact()` implémente cette vérification.

Un ancrage qui tomberait sous 1,0 signalerait une régression sérieuse : le
moteur aurait cessé d'être extractif.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from statistics import mean

# ── Normalisation ───────────────────────────────────────────────────────────


def normaliser(texte: str) -> str:
    """
    Forme comparable d'un texte : minuscules, accents retirés, ponctuation
    réduite à des espaces.

    Les accents sont retirés parce qu'un CV écrit « expérience » et une
    question « experience » désignent la même chose, et qu'une correspondance
    qui échoue sur un accent produit un faux négatif silencieux — exactement le
    défaut que ce projet cherche à éviter ailleurs.
    """
    texte = (texte or "").lower()
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def _chevauchement(a: str, b: str) -> float:
    """
    Proportion de mots de `a` (le passage attendu) présents dans `b`.

    Asymétrique volontairement : on veut savoir si le passage attendu est
    couvert par le passage récupéré, pas l'inverse. Un passage récupéré plus
    long qui contient l'attendu doit compter comme une réussite.
    """
    mots_a = set(normaliser(a).split())
    if not mots_a:
        return 0.0
    mots_b = set(normaliser(b).split())
    return len(mots_a & mots_b) / len(mots_a)


# Au-dessus de ce chevauchement, un passage récupéré est considéré comme
# correspondant au passage attendu. 0,7 tolère une coupure de découpage
# différente sans accepter un passage simplement voisin.
SEUIL_CORRESPONDANCE = 0.7


def correspond(passage_recupere: str, passage_attendu: str) -> bool:
    return _chevauchement(passage_attendu, passage_recupere) >= SEUIL_CORRESPONDANCE


def _rangs_pertinents(recuperes: list[str], attendus: list[str]) -> list[int]:
    """Rangs (à partir de 1) des passages récupérés jugés pertinents."""
    rangs = []
    for i, r in enumerate(recuperes, start=1):
        if any(correspond(r, a) for a in attendus):
            rangs.append(i)
    return rangs


# ── Métriques de récupération ───────────────────────────────────────────────


def taux_de_succes(recuperes: list[str], attendus: list[str], k: int) -> float:
    """1,0 si au moins un passage attendu figure dans les k premiers."""
    if not attendus:
        return 0.0
    return 1.0 if _rangs_pertinents(recuperes[:k], attendus) else 0.0


def rang_reciproque(recuperes: list[str], attendus: list[str]) -> float:
    """
    1/rang du premier passage pertinent.

    Distingue une récupération qui place le bon passage en tête (1,0) d'une
    autre qui le place troisième (0,33). Le taux de succès les confond.
    """
    rangs = _rangs_pertinents(recuperes, attendus)
    return 1.0 / rangs[0] if rangs else 0.0


def precision_a_k(recuperes: list[str], attendus: list[str], k: int) -> float:
    """Part des k premiers passages qui sont pertinents."""
    tranche = recuperes[:k]
    if not tranche:
        return 0.0
    return len(_rangs_pertinents(tranche, attendus)) / len(tranche)


def rappel_a_k(recuperes: list[str], attendus: list[str], k: int) -> float:
    """Part des passages attendus effectivement retrouvés dans les k premiers."""
    if not attendus:
        return 0.0
    tranche = recuperes[:k]
    trouves = sum(1 for a in attendus if any(correspond(r, a) for r in tranche))
    return trouves / len(attendus)


def precision_moyenne(recuperes: list[str], attendus: list[str]) -> float:
    """
    Précision moyenne aux rangs pertinents.

    Récompense le fait de grouper les bons passages en tête plutôt que de les
    disperser dans la liste.
    """
    rangs = _rangs_pertinents(recuperes, attendus)
    if not rangs:
        return 0.0
    return mean((i + 1) / rang for i, rang in enumerate(rangs))


# ── Métriques de réponse ────────────────────────────────────────────────────


def couverture_mots_cles(reponse: str, mots_cles: list[str]) -> float:
    """
    Part des mots-clés attendus présents dans la réponse.

    Pour « Quelles compétences possède le candidat ? » avec
    `["Python", "Angular"]`, renvoie 1,0 si les deux figurent dans l'extrait
    rendu, 0,5 si un seul.
    """
    if not mots_cles:
        return 0.0
    reponse_n = normaliser(reponse)
    presents = sum(1 for m in mots_cles if normaliser(m) in reponse_n)
    return presents / len(mots_cles)


def ancrage_exact(reponse: str, contextes: list[str]) -> float | None:
    """
    Vérifie que la réponse est bien un extrait d'un contexte récupéré.

    C'est l'équivalent exact de la « faithfulness » de Ragas, mais sans modèle
    juge : le moteur étant extractif, la réponse doit littéralement provenir
    d'un passage. Renvoie 1,0 ou 0,0 — il n'y a pas de demi-ancrage.

    Renvoie **None** lorsqu'il n'y a pas de réponse. C'est une distinction qui
    compte : une absence de réponse n'est pas une réponse infidèle. Compter un
    refus comme un ancrage nul ferait chuter la moyenne à chaque question
    légitimement sans réponse, et déclencherait une alerte sur un moteur
    parfaitement sain. Les valeurs None sont exclues de la moyenne.

    Une valeur inférieure à 1,0 sur les cas où une réponse EST rendue reste un
    signal fort : le moteur ne serait plus extractif, et la garantie « zéro
    hallucination » tomberait.
    """
    if not reponse.strip():
        return None
    reponse_n = normaliser(reponse)
    return 1.0 if any(reponse_n in normaliser(c) for c in contextes) else 0.0


# ── Agrégation ──────────────────────────────────────────────────────────────


@dataclass
class ResultatCas:
    """Mesures d'un cas de test."""

    identifiant: str
    question: str
    taux_succes: float
    rang_reciproque: float
    precision: float
    rappel: float
    precision_moyenne: float
    couverture: float
    #: None lorsque aucune réponse n'est rendue — l'ancrage est alors sans
    #: objet, et non nul. Voir `ancrage_exact`.
    ancrage: float | None
    confiance: float
    passages_recuperes: int

    def en_dict(self) -> dict:
        return {
            "id": self.identifiant,
            "hit_rate": round(self.taux_succes, 3),
            "mrr": round(self.rang_reciproque, 3),
            "precision_at_k": round(self.precision, 3),
            "recall_at_k": round(self.rappel, 3),
            "map": round(self.precision_moyenne, 3),
            "keyword_coverage": round(self.couverture, 3),
            "groundedness": None if self.ancrage is None else round(self.ancrage, 3),
            "confidence": round(self.confiance, 3),
            "retrieved": self.passages_recuperes,
        }


@dataclass
class Rapport:
    """Synthèse d'une campagne d'évaluation."""

    cas: list[ResultatCas] = field(default_factory=list)
    k: int = 3

    def ajouter(self, resultat: ResultatCas) -> None:
        self.cas.append(resultat)

    def _moyenne(self, attribut: str) -> float:
        """Moyenne sur les cas où la mesure est définie (None = sans objet)."""
        valeurs = [
            getattr(c, attribut) for c in self.cas
            if getattr(c, attribut) is not None
        ]
        return mean(valeurs) if valeurs else 0.0

    def _comptés(self, attribut: str) -> int:
        return sum(1 for c in self.cas if getattr(c, attribut) is not None)

    def synthese(self) -> dict:
        return {
            "cases": len(self.cas),
            "k": self.k,
            "hit_rate": round(self._moyenne("taux_succes"), 3),
            "mrr": round(self._moyenne("rang_reciproque"), 3),
            "precision_at_k": round(self._moyenne("precision"), 3),
            "recall_at_k": round(self._moyenne("rappel"), 3),
            "map": round(self._moyenne("precision_moyenne"), 3),
            "keyword_coverage": round(self._moyenne("couverture"), 3),
            "groundedness": round(self._moyenne("ancrage"), 3),
            # Le dénominateur de l'ancrage est publié : une moyenne de 1,0 sur
            # deux cas ne vaut pas une moyenne de 1,0 sur douze, et le lecteur
            # doit pouvoir faire la différence.
            "groundedness_applicable_cases": self._comptés("ancrage"),
            "mean_confidence": round(self._moyenne("confiance"), 3),
        }

    def echecs(self, seuil: float = 0.5) -> list[ResultatCas]:
        """
        Cas dont la récupération est en défaut.

        Ce sont eux qu'il faut lire : une moyenne satisfaisante peut masquer
        deux questions systématiquement manquées.
        """
        return [c for c in self.cas if c.taux_succes < seuil]
