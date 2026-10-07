# Évaluation de la qualité de récupération

Mesure ce que le moteur CAG ramène réellement, sur un jeu de test à vérité
terrain. Deux couches indépendantes :

| Couche | Dépendances | Toujours exécutable |
| --- | --- | --- |
| `metrics.py` — métriques de recherche d'information | **aucune** | oui |
| `ragas_runner.py` — métriques Ragas non-LLM | `requirements-eval.txt` | non |

La séparation est délibérée : Ragas tire un arbre de dépendances large et
fragile. L'évaluation de base doit rester possible quand il refuse de
s'installer — ce qui arrive.

---

## Lancer

```bash
cd backend
python -m evaluation.run_eval
```

Avec les métriques Ragas :

```bash
pip install -r evaluation/requirements-eval.txt
python -m evaluation.run_eval --ragas
```

Options : `--k 5` (passages récupérés), `--json rapport.json` (rapport
détaillé), `--seuil 0.8` (taux de succès minimal ; en deçà, code de sortie 1).

Le code de sortie est significatif : c'est ce qui permet d'en faire une porte
de qualité en intégration continue plutôt qu'un rapport que personne ne lit.

---

## Ce qui est mesuré

### Récupération — les bons passages sont-ils ramenés ?

| Métrique | Question à laquelle elle répond |
| --- | --- |
| `hit_rate` | Le bon passage figure-t-il dans les k premiers ? |
| `mrr` | À quel rang ? (1,0 = en tête, 0,33 = troisième) |
| `precision_at_k` | Quelle part des passages ramenés est pertinente ? |
| `recall_at_k` | Quelle part des passages attendus a été retrouvée ? |
| `map` | Les bons passages sont-ils groupés en tête ou dispersés ? |

### Réponse — l'extrait rendu est-il exploitable ?

| Métrique | Question à laquelle elle répond |
| --- | --- |
| `keyword_coverage` | Les termes attendus figurent-ils dans l'extrait ? |
| `groundedness` | L'extrait provient-il littéralement d'un passage ramené ? |

**`groundedness` mérite une explication.** C'est l'équivalent de la
*faithfulness* de Ragas, mais vérifiée **exactement**, par appartenance de
chaîne, sans modèle juge. C'est possible parce que le moteur est extractif : la
réponse EST un passage du contexte. Une valeur inférieure à 1,0 sur les cas
avec réponse signalerait que le moteur a cessé d'être extractif — et que la
garantie « zéro hallucination » est tombée.

La métrique vaut `None`, et non 0, lorsqu'aucune réponse n'est rendue : une
absence de réponse n'est pas une réponse infidèle. Les `None` sont exclus de la
moyenne, dont le dénominateur est publié
(`groundedness_applicable_cases`).

---

## Le jeu de test

12 cas sur 2 CV **synthétiques** (`dataset.py`).

> **Les CV sont inventés, et c'est impératif.** `backend/uploads/` contient
> 264 CV réels. Les employer ici ferait circuler des données personnelles dans
> un rapport, un journal d'exécution et le dépôt Git. Les personnes décrites
> dans `dataset.py` n'existent pas.

Trois familles de cas :

1. **Directs** — compétences, expérience, formation, langues. La réponse est
   dans le CV, avec un vocabulaire proche de la question.
2. **Reformulés** — « conteneurisation » pour *Docker*, « interfaces côté
   navigateur » pour *Angular*. Ces cas mesurent ce que le rapprochement
   sémantique apporte réellement : une correspondance littérale les manque
   tous.
3. **Négatifs** — questions dont la réponse n'est pas dans le CV. Le refus est
   un comportement attendu, et il se mesure. Un moteur évalué uniquement sur
   des questions auxquelles il peut répondre n'est pas évalué.

Ajouter un cas : une entrée dans `CAS`, avec ses `contextes_attendus` écrits
pour correspondre au découpage réel du moteur (phrases, lignes). Une vérité
terrain qu'aucun découpage ne peut produire mesurerait le découpage, pas la
récupération.

---

## Ragas : ce qu'il apporte, et ce qu'il n'apporte pas

Ragas est conçu pour les systèmes RAG **génératifs** : un modèle reformule les
passages, et il faut vérifier que la reformulation reste fidèle. Le moteur de
PIQBIT est **extractif**. Toutes ses métriques ne s'y appliquent donc pas.

| Métrique Ragas | Applicabilité ici |
| --- | --- |
| `context_precision` | **Retenue.** Les passages ramenés sont-ils les bons ? |
| `context_recall` | **Retenue.** A-t-on ramené tout ce qu'il fallait ? |
| `faithfulness` | **Écartée.** Vaut 1,0 par construction ; `groundedness` le vérifie littéralement, sans modèle juge. |
| `answer_relevancy` | **Écartée.** Exige un modèle juge externe, donc une clé d'API et un coût par appel — incohérent avec un moteur qui ne dépend d'aucun modèle externe. |

Les variantes retenues sont les **non-LLM** : elles s'exécutent hors ligne,
sans clé d'API et sans coût. Le rapport JSON porte ces exclusions dans
`ragas.excluded_metrics`, pour qu'un lecteur comprenne pourquoi `faithfulness`
n'y figure pas.

---

## Lien avec le traçage

Chaque cas ouvre une trace Langfuse et y attache ses scores (`hit_rate`,
`mrr`, `groundedness`). Une campagne devient donc un point de comparaison
daté : une dérive après changement de modèle d'embedding ou de découpage se
voit dans l'interface, au lieu de dormir dans un fichier.

Le traçage reste facultatif — sans clés, les appels sont des no-op et
l'évaluation fonctionne identiquement.

---

## Interpréter un résultat faible

Le premier chiffre obtenu dépend entièrement du **backend d'embedding** :

```
python -c "from app.services.embedding_service import embedding_service; print(embedding_service.backend)"
```

- `hash-v1` — repli déterministe, **non sémantique**. Il ne peut pas rapprocher
  « conteneurisation » de « Docker ». Un taux de succès faible est ici
  **attendu**, et ne dit rien de la qualité du moteur réel.
- `sentence-transformers` — modèle de plongement. C'est le seul backend dont le
  résultat vaut comme mesure de qualité.

Vérifiez donc toujours le backend avant de conclure. Un écart marqué entre les
deux est le résultat le plus parlant que produise ce harnais : il chiffre ce
que le rapprochement sémantique apporte.
