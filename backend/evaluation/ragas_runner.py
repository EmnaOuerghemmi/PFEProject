"""
Couche Ragas optionnelle.

CE QUE RAGAS APPORTE ICI — ET CE QU'IL N'APPORTE PAS.

Ragas est conçu pour les systèmes RAG **génératifs** : un modèle reformule les
passages récupérés, et il faut vérifier que la reformulation reste fidèle. Le
moteur de PIQBIT est **extractif** : il rend le passage tel quel. Toutes les
métriques de Ragas ne s'y appliquent donc pas, et le prétendre affaiblirait
l'évaluation plutôt que de la renforcer.

┌─────────────────────────┬─────────────────────────────────────────────────┐
│ Métrique Ragas          │ Applicabilité à un moteur extractif             │
├─────────────────────────┼─────────────────────────────────────────────────┤
│ faithfulness            │ **Sans objet.** Vaut 1,0 par construction : la  │
│                         │ réponse EST le contexte. `ancrage_exact()` le   │
│                         │ vérifie littéralement, sans modèle juge.        │
│ answer_relevancy        │ Mesure surtout la formulation. Exige un modèle  │
│                         │ juge, donc une clé d'API et un appel payant.    │
│                         │ Faible valeur ici.                              │
│ context_precision       │ **Pertinente.** Les passages ramenés sont-ils   │
│ context_recall          │ les bons ? C'est la vraie question du moteur.   │
│                         │ Variantes non-LLM disponibles avec référence.   │
└─────────────────────────┴─────────────────────────────────────────────────┘

Ce module n'expose donc que les métriques de **récupération**, dans leurs
variantes **non-LLM** : elles s'exécutent hors ligne, sans clé d'API et sans
coût, ce qui est cohérent avec un produit dont le moteur ne dépend d'aucun
modèle externe.

INSTALLATION. Ragas tire un arbre de dépendances large et fragile. Au moment de
l'écriture, `ragas==0.4.3` échoue à l'import avec `langchain-community>=0.4`
(il cherche `ChatVertexAI` à un emplacement supprimé). D'où l'épinglage dans
`requirements-eval.txt`, et d'où l'isolement de ce module : `metrics.py` reste
exécutable sans rien de tout cela.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def ragas_disponible() -> tuple[bool, str | None]:
    """
    Indique si Ragas est utilisable, et sinon pourquoi.

    Le contrôle va jusqu'à l'**instanciation** des métriques, et pas seulement
    à leur import. La distinction n'est pas théorique : les métriques non-LLM
    s'importent sans erreur puis lèvent à la construction si `rapidfuzz`
    manque, car elles s'appuient sur une distance de chaînes. Un contrôle
    limité à l'import annoncerait « disponible » puis échouerait en pleine
    campagne.

    Le message d'erreur est renvoyé tel quel : un échec de Ragas est presque
    toujours un conflit de version ou une dépendance absente, et le message
    l'indique précisément.
    """
    try:
        import ragas  # noqa: F401
        from ragas.metrics import (
            NonLLMContextPrecisionWithReference,
            NonLLMContextRecall,
        )

        NonLLMContextPrecisionWithReference()
        NonLLMContextRecall()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def evaluer_avec_ragas(cas_evalues: list[dict]) -> dict[str, Any]:
    """
    Applique les métriques de récupération non-LLM de Ragas.

    `cas_evalues` : liste de dictionnaires portant
        - `id`                  : identifiant du cas
        - `retrieved_contexts`  : passages ramenés par le moteur
        - `reference_contexts`  : passages attendus (vérité terrain)

    Les cas sans vérité terrain (refus attendu) sont ignorés : ces métriques
    comparent des ensembles de passages, et un ensemble attendu vide n'a pas
    de précision définie.
    """
    disponible, raison = ragas_disponible()
    if not disponible:
        return {"available": False, "reason": raison, "metrics": {}}

    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics import (
        NonLLMContextPrecisionWithReference,
        NonLLMContextRecall,
    )

    try:
        precision_metrique = NonLLMContextPrecisionWithReference()
        rappel_metrique = NonLLMContextRecall()
    except Exception as exc:  # pragma: no cover - dépendance manquante
        # Filet de sécurité : `ragas_disponible()` couvre déjà ce cas, mais une
        # campagne ne doit jamais s'interrompre sur une dépendance d'évaluation.
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}",
                "metrics": {}}

    precisions: list[float] = []
    rappels: list[float] = []
    par_cas: dict[str, dict[str, float]] = {}

    for entree in cas_evalues:
        references = entree.get("reference_contexts") or []
        if not references:
            continue
        recuperes = entree.get("retrieved_contexts") or []

        echantillon = SingleTurnSample(
            user_input=entree.get("question", ""),
            retrieved_contexts=recuperes,
            reference_contexts=references,
        )
        try:
            p = await precision_metrique.single_turn_ascore(echantillon)
            r = await rappel_metrique.single_turn_ascore(echantillon)
        except Exception as exc:  # pragma: no cover - dépend de la version
            logger.warning("Métrique Ragas ignorée pour %s : %s", entree.get("id"), exc)
            continue

        precisions.append(float(p))
        rappels.append(float(r))
        par_cas[entree["id"]] = {
            "context_precision": round(float(p), 3),
            "context_recall": round(float(r), 3),
        }

    def moyenne(valeurs: list[float]) -> float:
        return round(sum(valeurs) / len(valeurs), 3) if valeurs else 0.0

    return {
        "available": True,
        "reason": None,
        "evaluated_cases": len(par_cas),
        "metrics": {
            "context_precision": moyenne(precisions),
            "context_recall": moyenne(rappels),
        },
        "per_case": par_cas,
        # Énoncé dans le résultat lui-même : un lecteur du rapport JSON doit
        # comprendre pourquoi `faithfulness` n'y figure pas.
        "excluded_metrics": {
            "faithfulness": "sans objet — moteur extractif, ancrage vérifié "
                            "littéralement par groundedness",
            "answer_relevancy": "exige un modèle juge externe ; hors périmètre "
                                "d'un moteur sans dépendance à un LLM",
        },
    }
