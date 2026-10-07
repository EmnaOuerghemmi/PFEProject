"""
Tableau de bord commun : lecture, enregistrement, et qui voit quoi.

Une seule règle de visibilité, appliquée côté serveur à TOUT ce qui sort :

* l'administrateur voit tout et seul il modifie ;
* RH et recruteurs ne reçoivent que les graphiques dont l'audience les vise,
  et ne peuvent lire les DONNÉES d'une source que si un graphique visible
  pour eux l'utilise. Masquer une carte à l'écran ne suffirait pas : l'API
  resterait ouverte à qui l'appelle directement.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole
from app.schemas.dashboard_config import (
    BUILTIN_CARDS, Audience, DashboardConfig, DashboardConfigView,
)
from app.services.chart_series_service import chart_series_service

logger = logging.getLogger(__name__)

SETTING_KEY = "dashboard"

#: Quelles cartes fixes chaque jeu de données alimente — pour autoriser la
#: lecture d'un agrégat dès qu'une des cartes qui en dépendent est visible.
DATASET_CARDS: dict[str, tuple[str, ...]] = {
    "recruitment_summary": ("status", "jobs", "funnel", "performance"),
    "candidate_analytics": ("education",),
    "applications_timeline": ("evolution",),
}


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def can_see(audience: Audience, role: str) -> bool:
    """Vrai si `role` voit un graphique destiné à `audience`."""
    if role == UserRole.ADMIN:
        return True
    if audience == "ALL":
        return role in (UserRole.RH, UserRole.RECRUTEUR)
    return audience == role


def is_admin(user: User) -> bool:
    return _role(user) == UserRole.ADMIN


class DashboardConfigService:

    async def load(self, db: AsyncSession) -> DashboardConfig:
        """
        La composition commune.

        Avant elle, chaque utilisateur avait la sienne. Au premier accès, celle
        d'un administrateur qui avait personnalisé son tableau est reprise —
        réservée aux administrateurs, puisqu'elle était privée jusque-là :
        rien ne devient visible des autres sans que l'admin le décide.
        """
        ligne = await db.get(AppSetting, SETTING_KEY)
        if ligne is not None:
            return DashboardConfig.model_validate(ligne.value or {})

        admins = (await db.execute(
            select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at)
        )).scalars().all()
        for admin in admins:
            perso = DashboardConfig.model_validate(admin.dashboard_config or {})
            if perso.customized:
                for chart in perso.charts:
                    chart.visible_to = "ADMIN"
                return perso
        return DashboardConfig()

    async def save(self, db: AsyncSession, config: DashboardConfig, user: User) -> DashboardConfig:
        """Enregistre la composition. Les sources inconnues sont écartées ici."""
        connues = {d.id for d in chart_series_service.catalog().sources}
        config.charts = [c for c in config.charts if c.source_id in connues]
        config.builtin_visibility = {
            k: v for k, v in config.builtin_visibility.items() if k in BUILTIN_CARDS
        }
        valeur = config.model_dump(mode="json")
        ligne = await db.get(AppSetting, SETTING_KEY)
        if ligne is None:
            db.add(AppSetting(key=SETTING_KEY, value=valeur, updated_by=user.id))
        else:
            ligne.value = valeur
            ligne.updated_by = user.id
        await db.commit()
        logger.info("Tableau de bord commun mis à jour (%d graphique(s)).", len(config.charts))
        return config

    def view_for(self, config: DashboardConfig, user: User) -> DashboardConfigView:
        """La composition telle que `user` a le droit de la recevoir."""
        role = _role(user)
        visibilite = {k: config.builtin_visibility.get(k, "ALL") for k in BUILTIN_CARDS}
        if is_admin(user):
            return DashboardConfigView(
                charts=config.charts, customized=config.customized,
                builtin_visibility=visibilite, can_edit=True,
            )
        return DashboardConfigView(
            charts=[c for c in config.charts if can_see(c.visible_to, role)],
            customized=config.customized,
            builtin_visibility={k: v for k, v in visibilite.items() if can_see(v, role)},
            can_edit=False,
        )

    def can_read_source(self, config: DashboardConfig, user: User, source_id: str) -> bool:
        """Données d'une source : seulement si un graphique visible l'utilise."""
        if is_admin(user):
            return True
        role = _role(user)
        return any(c.source_id == source_id and can_see(c.visible_to, role) for c in config.charts)

    def can_read_dataset(self, config: DashboardConfig, user: User, dataset: str) -> bool:
        """Agrégat des cartes fixes : dès qu'une carte qui en dépend est visible."""
        if is_admin(user):
            return True
        role = _role(user)
        cartes: Iterable[str] = DATASET_CARDS.get(dataset, ())
        return any(can_see(config.builtin_visibility.get(k, "ALL"), role) for k in cartes)


dashboard_config_service = DashboardConfigService()
