"""
Format de série commun aux graphiques du tableau de bord.

Tant que chaque bloc du tableau de bord avait sa propre forme de données —
un `dash`/`offset` pour le donut, un `path` SVG pour l'évolution, des
pourcentages de largeur pour les barres — aucun sélecteur de type ne pouvait
fonctionner : changer la forme d'un graphique voulait dire réécrire son bloc.

Toute source expose désormais la même chose. Le champ qui porte la valeur du
module est `kind` : il dit quels types de graphique ont un sens sur cette
série. Un camembert de série temporelle n'est pas une option offerte à
l'utilisateur, c'est un défaut d'affichage.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SeriesKind(str, Enum):
    """
    Nature d'une série — ce qui décide des formes possibles.

    * `CATEGORIELLE` — des catégories sans ordre (statuts, offres). Barres et
      camembert. Une courbe relierait des points entre lesquels il n'y a rien.
    * `ORDONNEE` — des catégories qui ont un ordre (tranches d'expérience,
      bandes de score). Barres, et courbe acceptable puisque la progression
      d'une tranche à l'autre veut dire quelque chose.
    * `TEMPORELLE` — une valeur par date. Courbes, aires, barres. Un camembert
      détruirait l'axe du temps, qui est toute l'information.
    * `NUMERIQUE_2D` — deux dimensions numériques par point. Seul cas où un
      nuage de points a un sens.
    """
    CATEGORIELLE = "CATEGORIELLE"
    ORDONNEE = "ORDONNEE"
    TEMPORELLE = "TEMPORELLE"
    NUMERIQUE_2D = "NUMERIQUE_2D"


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    SCATTER = "scatter"


#: Ce que chaque nature autorise. Le sélecteur de type du navigateur n'offre
#: rien d'autre — c'est ici que la règle vit, et nulle part ailleurs.
ALLOWED_TYPES: dict[SeriesKind, list[ChartType]] = {
    SeriesKind.CATEGORIELLE: [ChartType.BAR, ChartType.PIE],
    SeriesKind.ORDONNEE: [ChartType.BAR, ChartType.LINE, ChartType.AREA],
    SeriesKind.TEMPORELLE: [ChartType.LINE, ChartType.AREA, ChartType.BAR],
    SeriesKind.NUMERIQUE_2D: [ChartType.SCATTER],
}


class SeriesPoint(BaseModel):
    """
    Un point.

    `label` est ce qui s'affiche, `x` ce qui positionne. Pour une série
    catégorielle les deux coïncident ; pour une série temporelle `x` est une
    date ISO et `label` sa forme lisible ; pour un nuage `x` est un nombre.
    """
    label: str
    x: str | float
    y: float
    #: Couleur imposée par la source (les statuts ont la leur). Sinon le
    #: navigateur pioche dans la palette du back-office.
    color: str | None = None


class ChartSeries(BaseModel):
    id: str
    label: str
    kind: SeriesKind
    points: list[SeriesPoint] = Field(default_factory=list)
    #: Légende de l'axe des valeurs — « candidatures », « employés »…
    unit: str | None = None
    #: Types possibles, dérivés de `kind`. Envoyés avec la série pour que le
    #: navigateur n'ait pas à refaire la règle de son côté.
    allowed_types: list[ChartType] = Field(default_factory=list)
    default_type: ChartType = ChartType.BAR
    generated_at: datetime | None = None


class SeriesDescriptor(BaseModel):
    """Une entrée du catalogue — ce que l'écran « Nouveau graphique » propose."""
    id: str
    label: str
    description: str
    kind: SeriesKind
    allowed_types: list[ChartType]
    default_type: ChartType
    #: Regroupement d'affichage dans le catalogue.
    category: str


class SeriesCatalog(BaseModel):
    sources: list[SeriesDescriptor]
