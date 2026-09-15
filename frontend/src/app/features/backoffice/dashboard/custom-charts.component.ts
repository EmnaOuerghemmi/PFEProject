import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  ChartSeries, ChartSeriesService, ChartType, CHART_TYPE_LABELS,
  DashboardChart, DashboardConfig, SeriesDescriptor,
} from '../../../core/services/chart-series.service';
import { ChartComponent } from '../../../shared/components/chart/chart.component';

/**
 * Tableau de bord composable — la partie que le RH construit lui-même.
 *
 * Trois choix de conception qui méritent d'être dits :
 *
 * 1. **Le sélecteur de type n'offre que ce que la donnée admet.** Un camembert
 *    de série temporelle détruirait l'axe du temps, qui est toute
 *    l'information. La règle vient du serveur avec la série — le navigateur ne
 *    la redevine pas.
 * 2. **Chaque graphique est indépendant.** Une source qui échoue laisse les
 *    autres en place : un tableau de bord qui disparaît en entier parce qu'une
 *    agrégation a un problème est pire qu'un trou.
 * 3. **La composition est propre à chaque utilisateur.** Deux RH ne suivent
 *    pas les mêmes chiffres, et un tableau partagé ferait de chaque ajout une
 *    négociation.
 */
interface Carte {
  config: DashboardChart;
  serie: ChartSeries | null;
  chargement: boolean;
  erreur: string;
}

/** Composition proposée à qui n'a jamais rien personnalisé. */
const PAR_DEFAUT: DashboardChart[] = [
  { id: 'd1', source_id: 'employees_by_age', chart_type: 'bar', title: null, span: 6 },
  { id: 'd2', source_id: 'employees_by_gender', chart_type: 'pie', title: null, span: 6 },
];

@Component({
  selector: 'app-custom-charts',
  standalone: true,
  imports: [CommonModule, FormsModule, ChartComponent],
  templateUrl: './custom-charts.component.html',
  styleUrls: ['./custom-charts.component.css'],
})
export class CustomChartsComponent implements OnInit {
  private service = inject(ChartSeriesService);

  cartes: Carte[] = [];
  catalogue: SeriesDescriptor[] = [];
  chargement = true;
  erreur = '';
  enregistrement = false;

  /** Écran d'ajout. */
  ajoutOuvert = false;
  sourceChoisie = '';
  typeChoisi: ChartType = 'bar';
  titreChoisi = '';

  readonly typeLabels = CHART_TYPE_LABELS;

  ngOnInit(): void {
    this.service.catalog().subscribe({
      next: (c) => {
        this.catalogue = c.sources;
        this.chargerConfiguration();
      },
      error: () => {
        this.chargement = false;
        this.erreur = 'Le catalogue des graphiques n\'a pas pu être chargé.';
      },
    });
  }

  private chargerConfiguration(): void {
    this.service.config().subscribe({
      next: (config) => {
        this.chargement = false;
        // `customized` distingue « jamais touché » de « vidé volontairement » :
        // sans lui, retirer son dernier graphique ferait réapparaître la
        // composition d'origine, et on ne pourrait jamais vider son tableau.
        const charts = config.customized ? config.charts : PAR_DEFAUT;
        this.cartes = charts.map((c) => this.enCarte(c));
        this.cartes.forEach((carte) => this.chargerSerie(carte));
      },
      error: () => {
        this.chargement = false;
        this.cartes = PAR_DEFAUT.map((c) => this.enCarte(c));
        this.cartes.forEach((carte) => this.chargerSerie(carte));
      },
    });
  }

  private enCarte(config: DashboardChart): Carte {
    return { config, serie: null, chargement: true, erreur: '' };
  }

  /** Une source qui échoue ne doit pas emporter les autres. */
  private chargerSerie(carte: Carte): void {
    carte.chargement = true;
    carte.erreur = '';
    this.service.series(carte.config.source_id).subscribe({
      next: (serie) => {
        carte.serie = serie;
        carte.chargement = false;
      },
      error: () => {
        carte.chargement = false;
        carte.erreur = 'Cette source est indisponible.';
      },
    });
  }

  // ── Modifier ────────────────────────────────────────────────────────────────

  /** Les types admis par CETTE série — jamais une liste fixe. */
  typesPossibles(carte: Carte): ChartType[] {
    if (carte.serie?.allowed_types?.length) return carte.serie.allowed_types;
    return this.catalogue.find((d) => d.id === carte.config.source_id)
      ?.allowed_types ?? ['bar'];
  }

  changerType(carte: Carte, type: ChartType): void {
    carte.config.chart_type = type;
    this.enregistrer();
  }

  retirer(carte: Carte): void {
    this.cartes = this.cartes.filter((c) => c !== carte);
    this.enregistrer();
  }

  elargir(carte: Carte): void {
    carte.config.span = carte.config.span >= 12 ? 6 : 12;
    this.enregistrer();
  }

  titre(carte: Carte): string {
    return carte.config.title
      || carte.serie?.label
      || this.catalogue.find((d) => d.id === carte.config.source_id)?.label
      || 'Graphique';
  }

  // ── Ajouter ─────────────────────────────────────────────────────────────────

  ouvrirAjout(): void {
    this.ajoutOuvert = true;
    this.sourceChoisie = '';
    this.titreChoisi = '';
  }

  surChoixSource(id: string): void {
    this.sourceChoisie = id;
    const source = this.catalogue.find((d) => d.id === id);
    // Le type par défaut de la source, pas le dernier choisi : une série
    // temporelle et un camembert n'ont pas les mêmes formes admissibles.
    this.typeChoisi = source?.default_type ?? 'bar';
  }

  get typesDeLaSourceChoisie(): ChartType[] {
    return this.catalogue.find((d) => d.id === this.sourceChoisie)
      ?.allowed_types ?? [];
  }

  get sourceSelectionnee(): SeriesDescriptor | undefined {
    return this.catalogue.find((d) => d.id === this.sourceChoisie);
  }

  ajouter(): void {
    if (!this.sourceChoisie) return;
    const carte = this.enCarte({
      id: `c${Date.now().toString(36)}`,
      source_id: this.sourceChoisie,
      chart_type: this.typeChoisi,
      title: this.titreChoisi.trim() || null,
      span: 6,
    });
    this.cartes = [...this.cartes, carte];
    this.chargerSerie(carte);
    this.ajoutOuvert = false;
    this.enregistrer();
  }

  /** Les catégories du catalogue, dans l'ordre d'apparition. */
  get categories(): string[] {
    return [...new Set(this.catalogue.map((d) => d.category))];
  }

  sourcesDe(categorie: string): SeriesDescriptor[] {
    return this.catalogue.filter((d) => d.category === categorie);
  }

  // ── Persistance ─────────────────────────────────────────────────────────────

  private enregistrer(): void {
    this.enregistrement = true;
    const config: DashboardConfig = {
      charts: this.cartes.map((c) => c.config),
      customized: true,
    };
    this.service.saveConfig(config).subscribe({
      next: () => { this.enregistrement = false; },
      error: () => {
        this.enregistrement = false;
        this.erreur = 'La composition n\'a pas pu être enregistrée.';
      },
    });
  }

  suivre(_: number, carte: Carte): string { return carte.config.id; }
}
