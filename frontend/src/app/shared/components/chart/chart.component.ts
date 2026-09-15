import {
  AfterViewInit, Component, ElementRef, Input, OnChanges, OnDestroy,
  SimpleChanges, ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Chart, ChartConfiguration, registerables } from 'chart.js';

import { ChartSeries, ChartType } from '../../../core/services/chart-series.service';

/**
 * Rendu générique d'une série, dans l'une des cinq formes.
 *
 * Avant ce composant, chaque bloc du tableau de bord était du SVG écrit à la
 * main : un cercle piloté par `stroke-dasharray` pour le camembert, un `path`
 * calculé en TypeScript pour l'évolution, des pourcentages de largeur pour les
 * barres. Six implémentations, aucune interchangeable — changer la forme d'un
 * graphique voulait dire le réécrire.
 *
 * Deux règles tiennent tout le composant :
 *
 * 1. **Les couleurs viennent des jetons CSS du back-office**, jamais de la
 *    palette par défaut de la bibliothèque. Sinon le tableau de bord porte deux
 *    identités visuelles côte à côte, et le thème sombre casse.
 * 2. **Aucun type n'est proposé ici.** La série dit ce qu'elle admet ; le
 *    composant se contente de dessiner ce qu'on lui demande.
 */
Chart.register(...registerables);

@Component({
  selector: 'app-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="ch-wrap">
      <canvas #toile *ngIf="aDesDonnees" role="img"
              [attr.aria-label]="descriptionAccessible"></canvas>

      <!-- Une série vide n'est pas une erreur : c'est le cas normal tant que la
           reprise des fiches employé n'a pas eu lieu. Le dire est plus utile
           que de dessiner des axes vides. -->
      <p class="ch-empty" *ngIf="!aDesDonnees">
        {{ messageVide }}
      </p>
    </div>
  `,
  styles: [`
    .ch-wrap { position: relative; width: 100%; height: 100%; min-height: 200px; }
    canvas { width: 100% !important; }
    .ch-empty {
      display: grid; place-items: center; height: 100%; min-height: 180px;
      margin: 0; padding: var(--s-5, 20px); text-align: center;
      font-size: var(--fs-sm, .8125rem); color: var(--c-muted, #788888);
    }
  `],
})
export class ChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('toile') toile?: ElementRef<HTMLCanvasElement>;

  @Input({ required: true }) series!: ChartSeries | null;
  @Input() type: ChartType = 'bar';
  /** Message affiché quand la série ne contient rien. */
  @Input() messageVide = 'Aucune donnée à afficher pour le moment.';

  private graphique?: Chart;
  private vuePrete = false;

  get aDesDonnees(): boolean {
    return !!this.series?.points?.length;
  }

  /**
   * Ce qu'un lecteur d'écran annonce. Un graphique sans description est
   * invisible pour qui ne le voit pas — et ces chiffres sont la page.
   */
  get descriptionAccessible(): string {
    if (!this.series) return '';
    const total = this.series.points.reduce((n, p) => n + p.y, 0);
    return `${this.series.label} — ${this.series.points.length} valeurs, total ${total}.`;
  }

  ngAfterViewInit(): void {
    this.vuePrete = true;
    this.redessiner();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['series'] || changes['type']) && this.vuePrete) {
      // Le canvas n'existe qu'une fois les données présentes : on laisse
      // Angular le créer avant de dessiner dedans.
      setTimeout(() => this.redessiner());
    }
  }

  ngOnDestroy(): void {
    this.graphique?.destroy();
  }

  // ── Rendu ───────────────────────────────────────────────────────────────────

  private redessiner(): void {
    this.graphique?.destroy();
    this.graphique = undefined;

    const toile = this.toile?.nativeElement;
    if (!toile || !this.series?.points?.length) return;

    this.graphique = new Chart(toile, this.configuration(this.series, this.type));
  }

  private configuration(serie: ChartSeries, type: ChartType): ChartConfiguration {
    const palette = this.palette();
    const encre = this.jeton('--c-ink-soft', '#3D4F4F');
    const grille = this.jeton('--c-line', '#ECE3CF');

    // « area » n'existe pas dans la bibliothèque : c'est une courbe remplie.
    const typeReel = type === 'area' ? 'line' : type;
    const parPart = type === 'pie';

    const couleurs = serie.points.map(
      (p, i) => p.color || palette[i % palette.length],
    );

    const donnees = type === 'scatter'
      ? serie.points.map((p) => ({ x: Number(p.x), y: p.y }))
      : serie.points.map((p) => p.y);

    return {
      type: typeReel as any,
      data: {
        labels: serie.points.map((p) => p.label),
        datasets: [{
          label: serie.unit || serie.label,
          data: donnees as any,
          // Une part de camembert a sa propre couleur ; une barre ou une
          // courbe garde celle de la série, sinon la forme perd sa lecture.
          backgroundColor: parPart || type === 'bar' || type === 'scatter'
            ? couleurs
            : this.transparence(palette[0], type === 'area' ? 0.18 : 0),
          borderColor: parPart ? this.jeton('--c-surface', '#FFFFFF') : palette[0],
          borderWidth: parPart ? 2 : 2,
          fill: type === 'area',
          tension: type === 'line' || type === 'area' ? 0.32 : 0,
          pointRadius: type === 'scatter' ? 5 : (type === 'bar' ? 0 : 3),
          borderRadius: type === 'bar' ? 6 : 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: this.mouvementReduit() ? false : { duration: 380 },
        plugins: {
          legend: {
            // Une légende sur une série unique répète le titre de la carte.
            display: parPart,
            position: 'bottom',
            labels: { color: encre, boxWidth: 12, padding: 14,
                      font: { size: 11, weight: 600 } },
          },
          tooltip: {
            callbacks: {
              label: (ctx: any) => {
                const valeur = type === 'scatter'
                  ? `${ctx.parsed.x} → ${ctx.parsed.y}`
                  : ctx.parsed.y ?? ctx.parsed;
                return `${ctx.label} : ${valeur}${serie.unit ? ' ' + serie.unit : ''}`;
              },
            },
          },
        },
        scales: parPart ? {} : {
          x: {
            ticks: { color: encre, font: { size: 11 }, maxRotation: 0,
                     autoSkipPadding: 14 },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { color: encre, font: { size: 11 }, precision: 0 },
            grid: { color: grille },
          },
        },
      },
    };
  }

  // ── Couleurs ────────────────────────────────────────────────────────────────

  /** Lue sur le document : le thème sombre change ces valeurs à chaud. */
  private jeton(nom: string, repli: string): string {
    if (typeof getComputedStyle !== 'function') return repli;
    const valeur = getComputedStyle(document.documentElement)
      .getPropertyValue(nom).trim();
    return valeur || repli;
  }

  private palette(): string[] {
    return [
      this.jeton('--c-nav', '#06222A'),
      this.jeton('--c-gold', '#10B981'),
      this.jeton('--c-info', '#5687B8'),
      this.jeton('--c-violet', '#8E6FB8'),
      this.jeton('--c-warn', '#D7903A'),
      this.jeton('--c-success', '#3DA76F'),
      this.jeton('--c-danger', '#D45B5B'),
      '#22D3EE',
    ];
  }

  private transparence(couleur: string, alpha: number): string {
    if (!alpha) return 'transparent';
    const hex = couleur.replace('#', '');
    if (hex.length !== 6) return couleur;
    const r = parseInt(hex.slice(0, 2), 16);
    const v = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${v}, ${b}, ${alpha})`;
  }

  private mouvementReduit(): boolean {
    return typeof matchMedia === 'function'
      && matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
}
