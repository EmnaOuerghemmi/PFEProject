"""
Harnais d'évaluation de la qualité de récupération.

POURQUOI UN PAQUET SÉPARÉ. Ragas tire langchain, datasets et des clients de
modèles — un arbre de dépendances large et fragile (la version installée
aujourd'hui exige `langchain-community` épinglé sous 0.4, sans quoi son import
échoue). Rien de cela n'a sa place dans l'image de production, qui est déjà
tenue au plus juste : la variante CPU de torch y est employée pour éviter
2,5 Go inutiles.

Ce paquet n'est donc **jamais importé par l'application**. Il s'exécute à la
demande, avec ses propres dépendances (`requirements-eval.txt`).

ORGANISATION.
  - `metrics.py`      : métriques de récupération, **sans aucune dépendance**.
                        Toujours exécutables, y compris hors ligne.
  - `dataset.py`      : jeu de test typé, sur des CV **synthétiques**.
  - `ragas_runner.py` : couche Ragas optionnelle, pour les métriques qui
                        s'appliquent réellement à un moteur extractif.
  - `run_eval.py`     : point d'entrée en ligne de commande.

La séparation entre `metrics.py` et `ragas_runner.py` est délibérée :
l'évaluation doit rester possible quand Ragas ne s'installe pas.
"""
