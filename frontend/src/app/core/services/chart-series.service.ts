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
  /** Ce que l'on compte — l'axe des ordonnées. */
  y_label: string;
  /** Selon quoi on le répartit — l'axe des abscisses. */
  x_label: string;
}

/**
 * Qui voit un graphique — choisi par l'administrateur, qui voit toujours tout.
 * ALL = RH et recruteurs.
 */
export type Audience = 'ALL' | 'RH' | 'RECRUTEUR' | 'ADMIN';

export const AUDIENCE_LABELS: Record<Audience, string> = {
  ALL: 'Tous',
  RH: 'RH',
  RECRUTEUR: 'Recruteurs',
  ADMIN: 'Administrateurs uniquement',
};

/** Les cartes fixes du tableau de bord, chacune avec sa visibilité. */
export type BuiltinCard = 'evolution' | 'status' | 'jobs' | 'funnel' | 'education' | 'performance';

export interface DashboardChart {
  id: string;
  source_id: string;
  chart_type: ChartType;
  title?: string | null;
  /** Largeur en colonnes, sur 12. */
  span: number;
  visible_to: Audience;
}

/**
 * Composition COMMUNE du tableau de bord, fixée par l'administrateur. Le
 * serveur la renvoie déjà filtrée pour le rôle qui la lit : un RH ou un
 * recruteur ne reçoit que les graphiques et cartes qui lui sont destinés.
 */
export interface DashboardConfig {
  charts: DashboardChart[];
  /** Distingue « jamais personnalisé » de « vidé volontairement ». */
  customized: boolean;
  /** Visibilité des cartes fixes. Pour un non-admin : seulement les visibles. */
  builtin_visibility: Partial<Record<BuiltinCard, Audience>>;
  /** Vrai pour l'administrateur seulement — lui seul compose le tableau. */
  can_edit?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ChartSeriesService {
  private api = inject(ApiService);

  /** Le catalogue des sources — réservé à l'admin (création de graphique). */
  catalog(): Observable<{ sources: SeriesDescriptor[] }> {
    return this.api.get<{ sources: SeriesDescriptor[] }>('dashboard/series');
  }

  /** Données d'une source — refusées si aucun graphique visible ne l'utilise. */
  series(sourceId: string): Observable<ChartSeries> {
    return this.api.get<ChartSeries>(`dashboard/series/${sourceId}`);
  }

  config(): Observable<DashboardConfig> {
    return this.api.get<DashboardConfig>('dashboard/config');
  }

  /** Enregistre la composition et la visibilité — administrateur seulement. */
  saveConfig(config: DashboardConfig): Observable<DashboardConfig> {
    return this.api.put<DashboardConfig>('dashboard/config', config);
  }
}
