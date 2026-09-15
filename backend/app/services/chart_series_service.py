"""
Catalogue de séries pour les graphiques du tableau de bord.

Un seul rôle : présenter toutes les sources de données sous **la même forme**,
pour qu'un graphique puisse changer de type sans que son bloc soit réécrit.
Les agrégations elles-mêmes restent là où elles étaient (`analytics_service`) ;
ce module les traduit.

Deux choses qu'il refuse de faire :

* **Proposer un type qui ment sur la donnée.** Chaque série déclare sa nature,
  et la nature décide des types. Un camembert de série temporelle détruirait
  l'axe du temps, qui est toute l'information.
* **Publier une tranche démographique trop petite.** Un « genre × service »
  dans un service de trois personnes ne montre pas une statistique, il montre
  une personne. Sous le seuil, la tranche est regroupée.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import application_status
from app.models.employee import GENDER_LABELS, Employee
from app.schemas.analytics import (
    ALLOWED_TYPES, ChartSeries, ChartType, SeriesCatalog, SeriesDescriptor,
    SeriesKind, SeriesPoint,
)
from app.services.analytics_service import analytics_service

logger = logging.getLogger(__name__)

#: Effectif minimal d'une tranche démographique pour être publiée telle quelle.
#: En dessous, la tranche rejoint « Autres » : à trois personnes dans un
#: service, une répartition par genre désigne des individus.
SEUIL_ANONYMAT = 5

#: Tranches d'âge. Bornes hautes exclues ; `None` = pas de borne.
TRANCHES_AGE: list[tuple[str, int, int | None]] = [
    ("Moins de 25 ans", 0, 25),
    ("25–34 ans", 25, 35),
    ("35–44 ans", 35, 45),
    ("45–54 ans", 45, 55),
    ("55 ans et plus", 55, None),
]


def _age(naissance: date | None, aujourdhui: date) -> int | None:
    """Âge révolu. Dupliquer le calcul du modèle serait pire que l'importer,
    mais le modèle travaille sur une instance ; ici on a des dates nues."""
    if not naissance:
        return None
    annees = aujourdhui.year - naissance.year
    if (aujourdhui.month, aujourdhui.day) < (naissance.month, naissance.day):
        annees -= 1
    return annees if annees >= 0 else None


class ChartSeriesService:
    """Traduit les agrégations existantes en séries interchangeables."""

    def catalog(self) -> SeriesCatalog:
        """Ce que l'écran « Nouveau graphique » propose."""
        return SeriesCatalog(sources=[
            SeriesDescriptor(
                id=identifiant, label=meta["label"], description=meta["description"],
                kind=meta["kind"], category=meta["category"],
                allowed_types=ALLOWED_TYPES[meta["kind"]],
                default_type=meta["default"],
            )
            for identifiant, meta in _SOURCES.items()
        ])

    async def series(self, db: AsyncSession, source_id: str) -> ChartSeries | None:
        """Une série par identifiant, ou `None` si la source est inconnue."""
        meta = _SOURCES.get(source_id)
        if not meta:
            return None
        points = await meta["builder"](self, db)
        return ChartSeries(
            id=source_id,
            label=meta["label"],
            kind=meta["kind"],
            points=points,
            unit=meta.get("unit"),
            allowed_types=ALLOWED_TYPES[meta["kind"]],
            default_type=meta["default"],
            generated_at=datetime.now(timezone.utc),
        )

    # ── Recrutement ───────────────────────────────────────────────────────────

    async def _statuts(self, db: AsyncSession) -> list[SeriesPoint]:
        resume = await analytics_service.recruitment_summary(db)
        par_statut = resume.get("applications_by_status", {})
        return [
            SeriesPoint(label=application_status.label(cle), x=cle, y=float(valeur))
            for cle, valeur in par_statut.items()
            if valeur                      # une part nulle encombre une légende
        ]

    async def _evolution(self, db: AsyncSession) -> list[SeriesPoint]:
        donnees = await analytics_service.applications_timeline(db, days=30)
        return [
            SeriesPoint(label=p["label"], x=p["date"], y=float(p["count"]))
            for p in donnees.get("series", [])
        ]

    async def _offres(self, db: AsyncSession) -> list[SeriesPoint]:
        resume = await analytics_service.recruitment_summary(db)
        return [
            SeriesPoint(label=o["title"], x=o["title"],
                        y=float(o["application_count"]))
            for o in resume.get("top_jobs", [])
        ]

    async def _experience(self, db: AsyncSession) -> list[SeriesPoint]:
        donnees = await analytics_service.candidate_analytics(db)
        return _depuis_compteurs(donnees.get("experience_buckets", []))

    async def _scores(self, db: AsyncSession) -> list[SeriesPoint]:
        donnees = await analytics_service.candidate_analytics(db)
        return _depuis_compteurs(donnees.get("score_bands", []))

    async def _formation(self, db: AsyncSession) -> list[SeriesPoint]:
        donnees = await analytics_service.candidate_analytics(db)
        return _depuis_compteurs(donnees.get("education", []))

    async def _competences(self, db: AsyncSession) -> list[SeriesPoint]:
        donnees = await analytics_service.candidate_analytics(db)
        return _depuis_compteurs(donnees.get("top_skills", []))

    # ── Effectif ──────────────────────────────────────────────────────────────

    async def _employes_par_age(self, db: AsyncSession) -> list[SeriesPoint]:
        """
        Répartition par tranche d'âge.

        Les employés sans date de naissance forment leur propre tranche plutôt
        que de disparaître : leur nombre est l'information la plus utile tant
        que la reprise des fiches existantes n'a pas eu lieu.
        """
        naissances = (await db.execute(
            select(Employee.birth_date).where(Employee.status != "inactive")
        )).scalars().all()

        aujourdhui = date.today()
        compteur: Counter = Counter()
        for naissance in naissances:
            age = _age(naissance, aujourdhui)
            if age is None:
                compteur["Non renseigné"] += 1
                continue
            for libelle, bas, haut in TRANCHES_AGE:
                if age >= bas and (haut is None or age < haut):
                    compteur[libelle] += 1
                    break

        ordre = [t[0] for t in TRANCHES_AGE] + ["Non renseigné"]
        return _anonymiser([
            SeriesPoint(label=libelle, x=libelle, y=float(compteur[libelle]))
            for libelle in ordre if compteur[libelle]
        ])

    async def _employes_par_genre(self, db: AsyncSession) -> list[SeriesPoint]:
        lignes = (await db.execute(
            select(Employee.gender, func.count(Employee.id))
            .where(Employee.status != "inactive")
            .group_by(Employee.gender)
        )).all()
        points = [
            SeriesPoint(
                label=GENDER_LABELS.get(genre or "", "Non renseigné"),
                x=genre or "NON_RENSEIGNE",
                y=float(nombre),
            )
            for genre, nombre in lignes
        ]
        return _anonymiser(points)

    async def _employes_par_service(self, db: AsyncSession) -> list[SeriesPoint]:
        lignes = (await db.execute(
            select(Employee.department, func.count(Employee.id))
            .where(Employee.status != "inactive")
            .group_by(Employee.department)
        )).all()
        return _anonymiser([
            SeriesPoint(label=service or "Non renseigné",
                        x=service or "—", y=float(nombre))
            for service, nombre in lignes
        ])

    async def _employes_par_contrat(self, db: AsyncSession) -> list[SeriesPoint]:
        lignes = (await db.execute(
            select(Employee.contract_type, func.count(Employee.id))
            .where(Employee.status != "inactive")
            .group_by(Employee.contract_type)
        )).all()
        return _anonymiser([
            SeriesPoint(label=contrat or "Non renseigné",
                        x=contrat or "—", y=float(nombre))
            for contrat, nombre in lignes
        ])

    async def _age_par_salaire(self, db: AsyncSession) -> list[SeriesPoint]:
        """
        Le seul nuage de points dont les données existent : âge × salaire.

        Deux précautions, et elles ne sont pas facultatives. Chaque point EST
        une personne : sans elles, un nuage de points est un annuaire.
        Sous le seuil d'anonymat, la série n'est pas publiée du tout ; au-delà,
        les salaires sont arrondis à la centaine.
        """
        lignes = (await db.execute(
            select(Employee.birth_date, Employee.salary).where(
                Employee.birth_date.is_not(None),
                Employee.salary.is_not(None),
                Employee.status != "inactive",
            )
        )).all()

        if len(lignes) < SEUIL_ANONYMAT:
            return []

        aujourdhui = date.today()
        points = []
        for naissance, salaire in lignes:
            age = _age(naissance, aujourdhui)
            if age is None:
                continue
            points.append(SeriesPoint(
                label=f"{age} ans",
                x=float(age),
                y=float(round(salaire / 100.0) * 100),
            ))
        return points


def _depuis_compteurs(entrees: list[dict]) -> list[SeriesPoint]:
    """Traduit la forme historique `[{label, count}]` en points."""
    return [
        SeriesPoint(label=e["label"], x=e["label"], y=float(e["count"]))
        for e in entrees
    ]


def _anonymiser(points: list[SeriesPoint]) -> list[SeriesPoint]:
    """
    Regroupe sous « Autres » les tranches trop petites pour être publiées.

    Un effectif de trois dans une tranche ne dit rien de statistique : il
    désigne trois personnes, que n'importe quel collègue reconnaîtra. Le
    regroupement n'est pas une précaution de forme, c'est ce qui sépare une
    répartition d'un trombinoscope.

    « Non renseigné » échappe au regroupement : ce n'est pas une catégorie de
    personnes, c'est une mesure de ce qui reste à saisir — et la masquer
    reviendrait à cacher le travail restant.
    """
    gardes, regroupes = [], 0.0
    for point in points:
        if point.y >= SEUIL_ANONYMAT or point.label == "Non renseigné":
            gardes.append(point)
        else:
            regroupes += point.y
    if regroupes:
        gardes.append(SeriesPoint(label="Autres", x="AUTRES", y=regroupes))
    return gardes


#: Le catalogue. `builder` est une méthode non liée : `series()` lui passe
#: l'instance. Déclarer les sources ici plutôt que par décorateur garde
#: l'inventaire lisible d'un coup d'œil.
_SOURCES: dict[str, dict] = {
    "applications_by_status": {
        "label": "Répartition des candidatures par statut",
        "description": "Où en sont les candidatures dans le parcours.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.PIE,
        "category": "Recrutement", "unit": "candidatures",
        "builder": ChartSeriesService._statuts,
    },
    "applications_timeline": {
        "label": "Évolution des candidatures",
        "description": "Candidatures déposées par jour, sur 30 jours.",
        "kind": SeriesKind.TEMPORELLE, "default": ChartType.AREA,
        "category": "Recrutement", "unit": "candidatures",
        "builder": ChartSeriesService._evolution,
    },
    "applications_by_job": {
        "label": "Candidatures par offre",
        "description": "Les cinq offres qui attirent le plus.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.BAR,
        "category": "Recrutement", "unit": "candidatures",
        "builder": ChartSeriesService._offres,
    },
    "candidates_by_experience": {
        "label": "Candidats par expérience",
        "description": "Années d'expérience extraites des CV.",
        "kind": SeriesKind.ORDONNEE, "default": ChartType.BAR,
        "category": "Candidats", "unit": "candidats",
        "builder": ChartSeriesService._experience,
    },
    "candidates_by_score": {
        "label": "Candidats par bande de score",
        "description": "Répartition des scores de CV.",
        "kind": SeriesKind.ORDONNEE, "default": ChartType.BAR,
        "category": "Candidats", "unit": "candidats",
        "builder": ChartSeriesService._scores,
    },
    "candidates_by_education": {
        "label": "Candidats par niveau d'études",
        "description": "Niveau extrait des CV analysés.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.BAR,
        "category": "Candidats", "unit": "candidats",
        "builder": ChartSeriesService._formation,
    },
    "top_skills": {
        "label": "Compétences les plus fréquentes",
        "description": "Les huit compétences les plus extraites des CV.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.BAR,
        "category": "Candidats", "unit": "occurrences",
        "builder": ChartSeriesService._competences,
    },
    "employees_by_age": {
        "label": "Effectif par tranche d'âge",
        "description": "Répartition des employés actifs par âge.",
        "kind": SeriesKind.ORDONNEE, "default": ChartType.BAR,
        "category": "Effectif", "unit": "employés",
        "builder": ChartSeriesService._employes_par_age,
    },
    "employees_by_gender": {
        "label": "Effectif par genre",
        "description": "Répartition des employés actifs par genre.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.PIE,
        "category": "Effectif", "unit": "employés",
        "builder": ChartSeriesService._employes_par_genre,
    },
    "employees_by_department": {
        "label": "Effectif par service",
        "description": "Répartition des employés actifs par service.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.BAR,
        "category": "Effectif", "unit": "employés",
        "builder": ChartSeriesService._employes_par_service,
    },
    "employees_by_contract": {
        "label": "Effectif par type de contrat",
        "description": "CDI, CDD, stages et alternances.",
        "kind": SeriesKind.CATEGORIELLE, "default": ChartType.PIE,
        "category": "Effectif", "unit": "employés",
        "builder": ChartSeriesService._employes_par_contrat,
    },
    "employees_age_salary": {
        "label": "Âge et salaire",
        "description": ("Un point par employé. Salaires arrondis à la centaine, "
                        "et rien n'est publié sous cinq personnes."),
        "kind": SeriesKind.NUMERIQUE_2D, "default": ChartType.SCATTER,
        "category": "Effectif", "unit": "TND",
        "builder": ChartSeriesService._age_par_salaire,
    },
}


chart_series_service = ChartSeriesService()
