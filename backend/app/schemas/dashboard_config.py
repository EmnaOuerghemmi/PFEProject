"""
Composition du tableau de bord, propre à chaque utilisateur.

Stockée dans une colonne JSON sur `users`, comme `notification_preferences` :
un tableau de bord est une préférence d'affichage, pas une donnée métier. Une
table dédiée n'aurait d'intérêt que si les graphiques devaient être partagés
entre RH — ce qui transformerait chaque ajout en négociation.

Le schéma est volontairement tolérant à la lecture : une configuration écrite
par une version antérieure doit continuer à s'ouvrir, quitte à ignorer ce
qu'elle ne comprend plus.
"""
from pydantic import BaseModel, Field

from app.schemas.analytics import ChartType


class DashboardChart(BaseModel):
    """Un graphique placé sur le tableau de bord."""

    #: Identifiant local, pour distinguer deux graphiques de la même source
    #: (la même répartition en barres et en camembert, par exemple).
    id: str = Field(..., min_length=1, max_length=64)
    #: Source du catalogue. Une source disparue est écartée à l'enregistrement.
    source_id: str = Field(..., min_length=1, max_length=80)
    chart_type: ChartType
    #: Titre choisi par l'utilisateur. Vide = celui de la source.
    title: str | None = Field(default=None, max_length=120)
    #: Largeur en colonnes de la grille (sur 12).
    span: int = Field(default=6, ge=3, le=12)


class DashboardConfig(BaseModel):
    """
    Le tableau de bord d'un utilisateur.

    `charts` vide ne veut pas dire « vide » mais « jamais personnalisé » :
    l'écran affiche alors la composition par défaut. Sans cette distinction,
    un utilisateur qui retire son dernier graphique verrait réapparaître la
    composition d'origine — et ne pourrait jamais vider son tableau.
    """
    charts: list[DashboardChart] = Field(default_factory=list, max_length=24)
    #: Posé au premier enregistrement. Distingue « jamais touché » de « vidé ».
    customized: bool = False

    def model_post_init(self, _context) -> None:
        if self.charts:
            self.customized = True
