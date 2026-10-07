"""
Observabilité applicative.

Séparé de `app/integrations/` volontairement : une intégration sert le métier
(agenda, visioconférence, modèles de langage), l'observabilité sert
l'exploitation. Les deux n'ont ni le même cycle de vie, ni les mêmes
conséquences en cas de panne — une intégration qui tombe dégrade une
fonctionnalité, un traceur qui tombe ne doit rien dégrader du tout.
"""
