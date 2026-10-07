"""
Point d'entrée en ligne de commande de l'évaluation.

    python -m evaluation.run_eval                 # métriques internes
    python -m evaluation.run_eval --ragas         # + métriques Ragas
    python -m evaluation.run_eval --json rapport.json
    python -m evaluation.run_eval --seuil 0.8     # code de sortie 1 sous le seuil

Le code de sortie est significatif : 0 si le taux de succès atteint le seuil,
1 sinon. C'est ce qui permet d'en faire une porte de qualité en intégration
continue plutôt qu'un rapport que personne ne lit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _formater_console(rapport, ragas: dict | None) -> str:
    s = rapport.synthese()
    lignes = [
        "",
        "═" * 68,
        "  ÉVALUATION DE LA RÉCUPÉRATION — PIQBIT",
        "═" * 68,
        f"  Cas évalués          : {s['cases']}   (k = {s['k']})",
        "",
        "  RÉCUPÉRATION",
        f"    Taux de succès     : {s['hit_rate']:.3f}",
        f"    Rang réciproque    : {s['mrr']:.3f}",
        f"    Précision@k        : {s['precision_at_k']:.3f}",
        f"    Rappel@k           : {s['recall_at_k']:.3f}",
        f"    Précision moyenne  : {s['map']:.3f}",
        "",
        "  RÉPONSE",
        f"    Couverture mots-clés : {s['keyword_coverage']:.3f}",
        f"    Ancrage (exact)      : {s['groundedness']:.3f}"
        f"   (sur {s['groundedness_applicable_cases']} cas avec réponse)",
        f"    Confiance moyenne    : {s['mean_confidence']:.3f}",
    ]

    if s["groundedness_applicable_cases"] and s["groundedness"] < 1.0:
        lignes += [
            "",
            "  ⚠ ANCRAGE SOUS 1,0 — le moteur ne serait plus strictement",
            "    extractif. La garantie « zéro hallucination » tombe.",
        ]

    echecs = rapport.echecs()
    if echecs:
        lignes += ["", f"  CAS EN ÉCHEC ({len(echecs)})"]
        for c in echecs:
            lignes.append(f"    · {c.identifiant:<26} conf={c.confiance:.3f}  {c.question}")

    if ragas is not None:
        lignes += ["", "  RAGAS"]
        if not ragas.get("available"):
            lignes.append(f"    Indisponible : {ragas.get('reason')}")
        else:
            m = ragas["metrics"]
            lignes += [
                f"    Cas évalués        : {ragas['evaluated_cases']}",
                f"    Context precision  : {m['context_precision']:.3f}",
                f"    Context recall     : {m['context_recall']:.3f}",
                "",
                "    Métriques écartées, et pourquoi :",
            ]
            for nom, motif in ragas.get("excluded_metrics", {}).items():
                lignes.append(f"      · {nom} : {motif}")

    lignes += ["═" * 68, ""]
    return "\n".join(lignes)


async def _principal(args) -> int:
    from evaluation import dataset as jeu
    from evaluation.runner import evaluer

    rapport = await evaluer(k=args.k)

    resultat_ragas = None
    if args.ragas:
        from evaluation.ragas_runner import evaluer_avec_ragas

        # Reconstruit les contextes récupérés pour Ragas, à partir du même
        # chemin que l'évaluation interne.
        from evaluation.runner import _recuperer

        entrees = []
        for cas in jeu.CAS:
            if not cas.contextes_attendus:
                continue
            cv = jeu.CORPUS[cas.cv]
            retenus, _, _ = await _recuperer(cv.texte, cas.question, args.k)
            entrees.append({
                "id": cas.identifiant,
                "question": cas.question,
                "retrieved_contexts": retenus,
                "reference_contexts": cas.contextes_attendus,
            })
        resultat_ragas = await evaluer_avec_ragas(entrees)

    print(_formater_console(rapport, resultat_ragas))

    if args.json:
        charge = {
            "summary": rapport.synthese(),
            "cases": [c.en_dict() for c in rapport.cas],
            "dataset": jeu.statistiques(),
            "ragas": resultat_ragas,
        }
        Path(args.json).write_text(
            json.dumps(charge, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Rapport écrit dans {args.json}")

    return 0 if rapport.synthese()["hit_rate"] >= args.seuil else 1


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Évalue la qualité de récupération du moteur CAG de PIQBIT."
    )
    parseur.add_argument("--k", type=int, default=3,
                         help="nombre de passages récupérés (défaut : 3)")
    parseur.add_argument("--ragas", action="store_true",
                         help="ajoute les métriques Ragas (dépendances séparées)")
    parseur.add_argument("--json", type=str, default=None,
                         help="écrit le rapport détaillé dans ce fichier")
    parseur.add_argument("--seuil", type=float, default=0.7,
                         help="taux de succès minimal ; en deçà, code de sortie 1")
    return asyncio.run(_principal(parseur.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
