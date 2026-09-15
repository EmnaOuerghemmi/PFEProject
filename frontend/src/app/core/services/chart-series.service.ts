import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

/**
 * Séries et composition du tableau de bord.
 *
 * Le service ne décide de rien : les types autorisés, les libellés et le seuil
 * d'anonymat viennent du serveur. C'est délibéré — une règle métier recopiée
 * dans le navigateur finit toujours par diverger de celle qui fait foi.
 */

export type ChartType = 'bar' | 'line' | 'area' | 'pie' | 'scatter';

export type SeriesKind =
  | 'CATEGORIELLE'   // catégories sans ordre — barres, camembert
  | 'ORDONNEE'       // catégories ordonnées — barres, courbe acceptable
  | 'TEMPORELLE'     // une valeur par date — courbes, aires, barres
  | 'NUMERIQUE_2D';  // deux dimensions numériques — nuage de points

export const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: 'Barres',
  line: 'Courbes',
  area: 'Aires',
  pie: 'Camembert',
  scatter: 'Nuage de points',
};

export interface SeriesPoint {
  label: string;
  x: string | number;
  y: number;
  color?: string | null;
}

export interface ChartSeries {
  id: string;
  label: string;
  kind: SeriesKind;
  points: SeriesPoint[];
  unit?: string | null;
  /** Ce que cette série admet — le sélecteur n'offre rien d'autre. */
  allowed_types: ChartType[];
  default_type: ChartType;
  generated_at?: string | null;
}

export interface SeriesDescriptor {
  id: string;
  label: string;
  description: string;
  kind: SeriesKind;
  allowed_types: ChartType[];
  default_type: ChartType;
  category: string;
}

export interface DashboardChart {
  id: string;
  source_id: string;
  chart_type: ChartType;
  title?: string | null;
  /** Largeur en colonnes, sur 12. */
  span: number;
}

export interface DashboardConfig {
  charts: DashboardChart[];
  /** Distingue « jamais personnalisé » de « vidé volontairement ». */
  customized: boolean;
}

@Injectable({ providedIn: 'root' })
export class ChartSeriesService {
  private api = inject(ApiService);

  /** Le catalogue des sources disponibles. */
  catalog(): Observable<{ sources: SeriesDescriptor[] }> {
    return this.api.get<{ sources: SeriesDescriptor[] }>('reports/series');
  }

  series(sourceId: string): Observable<ChartSeries> {
    return this.api.get<ChartSeries>(`reports/series/${sourceId}`);
  }

  config(): Observable<DashboardConfig> {
    return this.api.get<DashboardConfig>('reports/dashboard-config');
  }

  saveConfig(config: DashboardConfig): Observable<DashboardConfig> {
    return this.api.put<DashboardConfig>('reports/dashboard-config', config);
  }
}
