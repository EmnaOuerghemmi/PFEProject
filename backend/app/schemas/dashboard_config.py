"""
Composition du tableau de bord du back-office — commune, fixée par l'admin.

Elle était propre à chaque utilisateur. Elle est désormais UNIQUE : seul
l'administrateur ajoute, retire ou reformate un graphique, et décide pour
chacun qui peut le voir — tout le monde, les RH, les recruteurs, ou les
seuls administrateurs. Les autres rôles reçoivent la composition déjà
filtrée par le serveur : ce qu'ils n'ont pas le droit de voir ne leur
parvient pas, plutôt que d'être simplement masqué à l'écran.

Le schéma reste tolérant à la lecture : une configuration écrite par une
version antérieure doit continuer à s'ouvrir, quitte à ignorer ce qu'elle ne
comprend plus.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import ChartType

#: Qui voit un graphique. L'administrateur voit toujours tout.
#:   ALL       — RH et recruteurs ;
#:   RH        — les RH seulement ;
#:   RECRUTEUR — les recruteurs seulement ;
#:   ADMIN     — les administrateurs seulement.
Audience = Literal["ALL", "RH", "RECRUTEUR", "ADMIN"]

#: Les cartes fixes du tableau de bord, chacune avec sa propre visibilité.
BUILTIN_CARDS: tuple[str, ...] = (
    "evolution", "status", "jobs", "funnel", "education", "performance",
)


class DashboardChart(BaseModel):
    """Un graphique ajouté par l'administrateur."""

    #: Identifiant local, pour distinguer deux graphiques de la même source
    #: (la même répartition en barres et en camembert, par exemple).
    id: str = Field(..., min_length=1, max_length=64)
    #: Source du catalogue. Une source disparue est écartée à l'enregistrement.
    source_id: str = Field(..., min_length=1, max_length=80)
    chart_type: ChartType
    #: Titre choisi par l'administrateur. Vide = celui de la source.
    title: str | None = Field(default=None, max_length=120)
    #: Largeur en colonnes de la grille (sur 12).
    span: int = Field(default=6, ge=3, le=12)
    visible_to: Audience = "ALL"


class DashboardConfig(BaseModel):
    """
    La composition commune du tableau de bord.

    `charts` vide ne veut pas dire « vide » mais « jamais personnalisé » :
    l'écran affiche alors la composition par défaut. Sans cette distinction,
    un administrateur qui retire son dernier graphique verrait réapparaître la
    composition d'origine — et ne pourrait jamais vider le tableau.
    """
    charts: list[DashboardChart] = Field(default_factory=list, max_length=24)
    #: Posé au premier enregistrement. Distingue « jamais touché » de « vidé ».
    customized: bool = False
    #: Visibilité des cartes fixes (`BUILTIN_CARDS`). Une carte absente vaut ALL.
    builtin_visibility: dict[str, Audience] = Field(default_factory=dict)

    def model_post_init(self, _context) -> None:
        if self.charts:
            self.customized = True


class DashboardConfigView(DashboardConfig):
    """
    Ce que reçoit l'écran : la composition, filtrée pour le rôle qui la lit,
    et le droit de la modifier. Pour un non-administrateur, `charts` et
    `builtin_visibility` ne contiennent QUE ce qu'il peut voir.
    """
    can_edit: bool = False
