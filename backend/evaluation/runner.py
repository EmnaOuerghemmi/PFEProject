"""
Exécution du jeu de test contre le moteur de récupération réel.

CE QUI EST ÉVALUÉ. Le chemin exact du produit : découpage du CV par
`_split_passages`, encodage par `embedding_service`, classement par cosinus,
seuil de confiance `MIN_CONFIDENCE`. Aucune réimplémentation — une évaluation
qui mesurerait une copie du moteur ne mesurerait rien d'utile.

Le corpus, lui, est synthétique et tenu en mémoire : l'évaluation ne touche ni
la base de données, ni `backend/uploads/`. Elle est donc exécutable partout, y
compris en intégration continue, sans données personnelles.

LIEN AVEC LE TRAÇAGE. Chaque cas ouvre une trace Langfuse et y attache ses
scores. C'est ce qui rend l'évaluation utile dans la durée : une campagne
devient un point de comparaison daté, et une dérive après changement de modèle
d'embedding se voit dans l'interface plutôt que dans un fichier oublié.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from app.observability.langfuse_client import (
    TYPE_RETRIEVER,
    langfuse_client,
)
from app.observability.redaction import metadonnees_sures
from app.services.cag_service import MIN_CONFIDENCE, _split_passages
from app.services.embedding_service import embedding_service
from evaluation import dataset as jeu
from evaluation.metrics import (
    ResultatCas,
    Rapport,
    ancrage_exact,
    couverture_mots_cles,
    precision_a_k,
    precision_moyenne,
    rang_reciproque,
    rappel_a_k,
    taux_de_succes,
)


async def _recuperer(
    texte_cv: str, question: str, k: int
) -> tuple[list[str], float, list[float]]:
    """
    Reproduit le chemin de récupération du moteur sur un corpus en mémoire.

    Emploie les mêmes fonctions que la production : même découpage, même
    encodeur, même mesure de similarité, même seuil.
    """
    passages = _split_passages(texte_cv)
    if not passages:
        return [], 0.0, []

    vecteurs = await embedding_service.aembed_many(passages)
    qv = await embedding_service.aembed(question)

    classes = sorted(
        zip((embedding_service.cosine(qv, v) for v in vecteurs), passages),
        key=lambda t: t[0],
        reverse=True,
    )
    meilleur = classes[0][0] if classes else 0.0
    retenus = [p for s, p in classes[:k] if s >= MIN_CONFIDENCE]
    scores = [round(s, 4) for s, _ in classes[:k]]
    return retenus, meilleur, scores


async def evaluer(k: int = 3, sur_cas: Callable[[ResultatCas], None] | None = None) -> Rapport:
    """
    Exécute le jeu complet et renvoie le rapport.

    `sur_cas` permet d'afficher la progression sans coupler ce module à une
    sortie console.
    """
    rapport = Rapport(k=k)

    with langfuse_client.trace(
        "run-retrieval-evaluation",
        # Une campagne prend le jeu de test en entrée : sans cela, la trace
        # racine s'ouvre sur une colonne vide et n'apprend rien au relecteur.
        entree={"dataset": jeu.statistiques(), "k": k},
        metadata={
            "k": k,
            "embedding_backend": embedding_service.backend,
            **jeu.statistiques(),
        },
        tags=["evaluation", "retrieval"],
    ) as trace_campagne:

        for cas in jeu.CAS:
            cv = jeu.CORPUS[cas.cv]

            with langfuse_client.trace(
                "evaluate-retrieval-case",
                # Les questions du jeu sont SYNTHÉTIQUES : elles peuvent être
                # tracées en clair, et c'est précieux — la trace devient
                # lisible sans avoir à ouvrir le fichier du jeu de test.
                # Le masquage reste appliqué au CV, qui, lui, ne sort jamais.
                entree={
                    "question": cas.question,
                    "case_id": cas.identifiant,
                    "expects_refusal": cas.refus_attendu,
                },
                metadata={
                    "case_id": cas.identifiant,
                    "cv_id": cv.identifiant,
                    "expects_refusal": cas.refus_attendu,
                    "k": k,
                },
                tags=["evaluation", "retrieval", cv.identifiant],
            ) as trace_cas:

                with trace_cas.span("retrieve-cv-passages", type_=TYPE_RETRIEVER,
                                    entree={"question": cas.question, "k": k},
                                    modele=embedding_service.backend) as etape:
                    retenus, meilleur, scores = await _recuperer(cv.texte, cas.question, k)
                    etape.sortie(**metadonnees_sures(
                        retrieved=len(retenus),
                        best_score=round(meilleur, 4),
                        top_scores=scores,
                    ))

                resultat = _mesurer(cas, retenus, meilleur, k)
                rapport.ajouter(resultat)

                # Les scores attachés à la trace sont ce qui permettra de
                # comparer deux campagnes dans le temps.
                trace_cas.score("hit_rate", resultat.taux_succes)
                trace_cas.score("mrr", resultat.rang_reciproque)
                trace_cas.score("groundedness", resultat.ancrage)
                trace_cas.sortie(**metadonnees_sures(
                    outcome="ok" if resultat.taux_succes >= 0.5 else "miss",
                    confidence=round(meilleur, 4),
                ))

                if sur_cas:
                    sur_cas(resultat)

        synthese = rapport.synthese()
        for nom in ("hit_rate", "mrr", "precision_at_k", "recall_at_k",
                    "map", "keyword_coverage", "groundedness"):
            trace_campagne.score(nom, synthese[nom])
        trace_campagne.sortie(**metadonnees_sures(**synthese))

    langfuse_client.flush()
    return rapport


def _mesurer(cas: jeu.CasDeTest, retenus: list[str], meilleur: float, k: int) -> ResultatCas:
    """Applique les métriques à un cas, selon qu'il attend une réponse ou un refus."""
    if cas.refus_attendu:
        # Pour un cas négatif, « réussir » signifie ne RIEN retenir au-dessus
        # du seuil. Appliquer les métriques de récupération n'aurait pas de
        # sens : il n'y a pas de passage à trouver.
        a_refuse = meilleur < MIN_CONFIDENCE or not retenus
        valeur = 1.0 if a_refuse else 0.0
        return ResultatCas(
            identifiant=cas.identifiant,
            question=cas.question,
            taux_succes=valeur,
            rang_reciproque=valeur,
            precision=valeur,
            rappel=valeur,
            precision_moyenne=valeur,
            couverture=valeur,
            # Sans objet sur un refus : rien n'est extrait, donc rien ne peut
            # être infidèle. `None` exclut le cas de la moyenne, au lieu de la
            # tirer vers le bas.
            ancrage=None,
            confiance=meilleur,
            passages_recuperes=len(retenus),
        )

    reponse = retenus[0] if retenus else ""
    return ResultatCas(
        identifiant=cas.identifiant,
        question=cas.question,
        taux_succes=taux_de_succes(retenus, cas.contextes_attendus, k),
        rang_reciproque=rang_reciproque(retenus, cas.contextes_attendus),
        precision=precision_a_k(retenus, cas.contextes_attendus, k),
        rappel=rappel_a_k(retenus, cas.contextes_attendus, k),
        precision_moyenne=precision_moyenne(retenus, cas.contextes_attendus),
        couverture=couverture_mots_cles(reponse, cas.mots_cles),
        ancrage=ancrage_exact(reponse, retenus),
        confiance=meilleur,
        passages_recuperes=len(retenus),
    )


def evaluer_sync(k: int = 3) -> Rapport:
    """Enveloppe synchrone, pour l'appel en ligne de commande."""
    return asyncio.run(evaluer(k=k))
