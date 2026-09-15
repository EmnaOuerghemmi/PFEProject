"""
Contrôle d'accès par rôle, porté par Casbin.

Ce que ce module change par rapport à l'ancien `require_role(...)` :

* **Une seule source de vérité.** Les permissions vivaient éparpillées dans
  une cinquantaine de décorateurs `require_role(ADMIN, RH_MANAGER)`. Répondre
  à « qu'a le droit de faire un recruteur ? » demandait de relire tous les
  endpoints, et ajouter un rôle imposait de tous les rouvrir. Elles tiennent
  maintenant dans `rbac_policy.csv`, relisible d'un coup d'œil.
* **L'endpoint déclare son intention, pas la liste des élus.** `require("jobs",
  "write")` dit ce que la route engage ; qui y a droit est une décision de
  politique, prise ailleurs.
* **L'héritage est explicite.** `g, RH, RECRUTEUR` remplace la répétition des
  mêmes rôles dans chaque décorateur — et supprime la dérive où un rôle
  finissait oublié sur une route et pas sur sa voisine.

Le refus reste le défaut : une ressource absente de la politique est
interdite à tout le monde sauf à l'administrateur (`p, ADMIN, *, *`).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Annotated

import casbin
from fastapi import Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

_MODELE = Path(__file__).with_name("rbac_model.conf")
_POLITIQUE = Path(__file__).with_name("rbac_policy.csv")

_enforcer: casbin.Enforcer | None = None
_verrou = threading.Lock()


def enforcer() -> casbin.Enforcer:
    """
    L'instance Casbin, chargée une seule fois.

    Construite à la demande plutôt qu'à l'import : un fichier de politique
    illisible ferait autrement échouer l'import du module, donc le démarrage
    de l'API, avec une trace d'import peu parlante.
    """
    global _enforcer
    if _enforcer is None:
        with _verrou:
            if _enforcer is None:
                _enforcer = casbin.Enforcer(str(_MODELE), str(_POLITIQUE))
                logger.info(
                    "Politique d'accès chargée (%d règles, %d liens d'héritage)",
                    len(_enforcer.get_policy()), len(_enforcer.get_grouping_policy()),
                )
    return _enforcer


def autorise(role: str | None, ressource: str, action: str) -> bool:
    """Vrai si ce RÔLE peut faire cette action sur cette ressource."""
    if not role:
        return False
    return enforcer().enforce(role, ressource, action)


def permissions_de(role: str | None) -> dict[str, list[str]]:
    """
    Toutes les permissions effectives d'un rôle, héritage compris.

    Sert à l'interface : le front s'en sert pour n'afficher que les écrans
    réellement accessibles, au lieu d'ouvrir une page qui se remplira d'un
    403. C'est un CONFORT d'affichage — la décision fait toujours autorité
    côté serveur, sur chaque requête.
    """
    if not role:
        return {}
    e = enforcer()
    par_ressource: dict[str, set[str]] = {}
    for sujet, ressource, action in e.get_policy():
        # `*` n'est pas énumérable : on ne le déplie pas, on le signale tel
        # quel et l'appelant comprend « tout ».
        if sujet != role and not e.has_role_for_user(role, sujet):
            continue
        par_ressource.setdefault(ressource, set()).add(action)
    return {r: sorted(a) for r, a in sorted(par_ressource.items())}


def require(ressource: str, action: str):
    """
    Dépendance FastAPI : 403 si le rôle de l'appelant n'a pas la permission.

    `is_superuser` court-circuite la politique, comme avant : c'est le compte
    de secours qui doit rester utilisable même si la politique est mal
    écrite — précisément le moment où on en a besoin.
    """
    async def _verifier(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.is_superuser:
            return user
        if not autorise(user.role, ressource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action non autorisée pour votre rôle ({ressource}:{action}).",
            )
        return user
    return _verifier
