import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DashboardService } from '../services/dashboard.service';
import { AuthService } from '../../../core/services/auth.service';
import { RecruitmentSummary, CandidateAnalytics, LabelCount, ApplicationsTimeline } from '../../../core/services/recruitment.service';
import { APPLICATION_STATUS_META } from '../../../core/services/recruitment.service';
import { ChartComponent } from '../../../shared/components/chart/chart.component';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';
import {
  AUDIENCE_LABELS, Audience, BuiltinCard, ChartSeries, ChartSeriesService, ChartType,
  CHART_TYPE_LABELS, DashboardChart, SeriesDescriptor,
} from '../../../core/services/chart-series.service';
import { VisibilityMenuComponent } from './visibility-menu.component';

/** Un graphique ajouté par l'administrateur — une carte de plus, au même
 * design que les quatre premières, retirable, et visible du rôle qu'il choisit. */
interface GraphiquePersonnalise {
  id: string;
  sourceId: string;
  titre: string | null;
  type: ChartType;
  visibleTo: Audience;
  serie: ChartSeries | null;
  chargement: boolean;
  erreur: string;
  /** Figé ici plutôt que recalculé dans le gabarit — voir la note sur
      `axesYOptions` : un tableau reconstruit à chaque cycle ne converge pas. */
  typeOptions: SelectOption[];
}

interface Bar { label: string; count: number; pct: number; }
interface FunnelStage { label: string; count: number; pct: number; }

interface DonutSeg {
  key: string;
  label: string;
  value: number;
  color: string;
  percent: number;
  dash: string;
  offset: number;
}

@Component({
  selector: 'app-backoffice-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, ChartComponent, SelectComponent, VisibilityMenuComponent],
  templateUrl: './backoffice-dashboard.component.html',
  styleUrls: ['./backoffice-dashboard.component.css'],
})
export class BackofficeDashboardComponent implements OnInit {
  stats = { totalJobs: 0, totalApplications: 0, totalHires: 0, activeUsers: 0, newUsers: 0 };
  summary: RecruitmentSummary | null = null;
  analytics: CandidateAnalytics | null = null;
  isSuperAdmin = false;
  isLoading = true;

  // Niveau d'éducation — seule carte encore affichée par cette liste ;
  // expérience et score IA ont été retirés du tableau de bord.
  eduBars: Bar[] = [];
  topSkills: LabelCount[] = [];

  // Évolution des candidatures — la donnée brute. Sa mise en points pour
  // app-chart se fait dans `evolutionSeries`, au moment de l'affichage : le
  // tracé lui-même (coordonnées SVG) n'existe plus depuis que la carte est
  // rendue par app-chart plutôt qu'à la main.
  timeline: ApplicationsTimeline | null = null;

  // Pipeline funnel
  funnel: FunnelStage[] = [];

  // Charts
  donut: DonutSeg[] = [];
  donutTotal = 0;
  topJobs: { title: string; count: number; pct: number }[] = [];
  readonly R = 54;
  readonly C = 2 * Math.PI * 54; // circumference

  // Dérivée de la table partagée : trois composants tenaient chacun leur copie,
  // et les trois divergeaient. Celle-ci ignorait les quatre statuts de test, si
  // bien qu'un candidat en cours de test disparaissait de la légende.
  readonly statusMeta = APPLICATION_STATUS_META;

  // ── Forme choisie pour les quatre graphiques du haut ──
  //
  // Ces quatre cartes restent EXACTEMENT à leur place — même titre, même
  // badge, même emplacement — seule leur représentation change. `app-chart`
  // (Chart.js) est réutilisé plutôt que d'écrire un tracé SVG par forme : les
  // données qu'il reçoit sont celles déjà calculées pour l'affichage
  // d'origine (`timeline`, `donut`, `topJobs`, `funnel`), reformatées en
  // points plutôt que recalculées.
  readonly typeLabels = CHART_TYPE_LABELS;
  evolutionType: ChartType = 'area';
  statusType: ChartType = 'pie';
  jobsType: ChartType = 'bar';
  funnelType: ChartType = 'bar';
  readonly evolutionTypes: ChartType[] = ['area', 'line', 'bar'];
  readonly statusTypes: ChartType[] = ['pie', 'bar'];
  readonly jobsTypes: ChartType[] = ['bar', 'pie'];
  // Étapes cumulatives (une candidature « en entretien » l'est aussi
  // « examinée ») : le camembert n'a pas de sens ici, ses parts se
  // recouvriraient.
  readonly funnelTypes: ChartType[] = ['bar', 'line', 'area'];

  // `app-select` attend des paires {value, label} plutôt qu'une liste de
  // types nus (comme le faisait le <select> natif avec <option [value]>) :
  // précalculées une fois, pour ne pas reconstruire ces petits tableaux à
  // chaque cycle de détection de changement.
  readonly evolutionTypeOptions = this.versOptions(this.evolutionTypes);
  readonly statusTypeOptions = this.versOptions(this.statusTypes);
  readonly jobsTypeOptions = this.versOptions(this.jobsTypes);
  readonly funnelTypeOptions = this.versOptions(this.funnelTypes);

  // ── Graphiques ajoutés par le RH ──
  //
  // Une carte de plus dans la même rangée que les quatre fixes, au même
  // design — pas une seconde zone séparée. La composition (quelles sources,
  // quelle forme) est propre à chaque compte et survit à la reconnexion :
  // `dashboard_config` est déjà le mécanisme prévu pour ça.
  catalogue: SeriesDescriptor[] = [];
  graphiquesPersonnalises: GraphiquePersonnalise[] = [];

  // ── Composition commune et visibilité ──
  //
  // Le tableau de bord est COMPOSÉ PAR L'ADMINISTRATEUR, qui choisit pour
  // chaque carte qui la voit. Le serveur renvoie la composition déjà filtrée
  // par rôle : `visibiliteCartes` ne contient, pour un RH ou un recruteur,
  // que les cartes qui lui sont destinées. `peutModifier` vient aussi du
  // serveur — l'interface n'en déduit rien par elle-même.
  peutModifier = false;
  configChargee = false;
  visibiliteCartes: Partial<Record<BuiltinCard, Audience>> = {};
  /** Audience du graphique en cours de création. */
  audienceChoisie: Audience = 'ALL';
  readonly audienceOptions: SelectOption[] =
    (['ALL', 'RH', 'RECRUTEUR', 'ADMIN'] as Audience[]).map(a => ({ value: a, label: AUDIENCE_LABELS[a] }));
  panneauOuvert = false;
  axeY = '';
  sourceChoisie = '';
  typeChoisi: ChartType = 'bar';
  titreChoisi = '';
  /** La donnée réelle de la source choisie, pour l'aperçu dans le panneau —
   * indépendante des graphiques déjà créés, qui ont chacun la leur. */
  previewSerie: ChartSeries | null = null;
  previewChargement = false;

  constructor(
    private dashboardService: DashboardService,
    private authService: AuthService,
    private chartSeries: ChartSeriesService,
  ) {}

  ngOnInit(): void {
    this.isSuperAdmin = this.authService.getCurrentUser()?.is_superuser || false;
    // La composition d'abord : elle dit quelles cartes ce rôle voit, donc
    // quelles données demander — inutile de réclamer celles qu'il ne verra pas.
    this.chartSeries.config().subscribe({
      next: cfg => {
        this.peutModifier = !!cfg.can_edit;
        this.visibiliteCartes = cfg.builtin_visibility || {};
        this.configChargee = true;
        if (this.peutModifier) {
          this.chartSeries.catalog().subscribe({
            next: c => { this.catalogue = c.sources; this.rafraichirOptionsPanneau(); },
            error: () => {},
          });
        }
        if (cfg.customized) {
          this.graphiquesPersonnalises = cfg.charts.map(c => this.enGraphique(c));
          this.graphiquesPersonnalises.forEach(g => this.chargerSerie(g));
        }
        this.load();
      },
      error: () => { this.configChargee = true; this.isLoading = false; },
    });
  }

  /** Vrai si la carte fixe est visible pour l'utilisateur connecté. */
  voit(carte: BuiltinCard): boolean {
    return this.peutModifier || carte in this.visibiliteCartes;
  }

  audienceCarte(carte: BuiltinCard): Audience {
    return this.visibiliteCartes[carte] ?? 'ALL';
  }

  /** Rien n'est partagé avec ce rôle : l'écran le dit plutôt que de rester vide. */
  get rienDePartage(): boolean {
    return this.configChargee && !this.peutModifier
      && !Object.keys(this.visibiliteCartes).length && !this.graphiquesPersonnalises.length;
  }

  changerVisibiliteCarte(carte: BuiltinCard, audience: Audience): void {
    this.visibiliteCartes = { ...this.visibiliteCartes, [carte]: audience };
    this.enregistrerComposition();
  }

  changerVisibiliteGraphique(g: GraphiquePersonnalise, audience: Audience): void {
    g.visibleTo = audience;
    this.enregistrerComposition();
  }

  load(): void {
    this.isLoading = true;

    this.dashboardService.getDashboardStats().subscribe({
      next: d => this.stats = {
        totalJobs: d.total_jobs || 0,
        totalApplications: d.total_applications || 0,
        totalHires: d.total_hires || 0,
        activeUsers: d.active_users || 0,
        newUsers: d.new_users || 0,
      },
      error: () => {},
    });

    // Chaque agrégat n'est demandé que si une carte visible en dépend : le
    // serveur le refuserait de toute façon (403) pour un rôle non autorisé.
    const cartesDuResume: BuiltinCard[] = ['status', 'jobs', 'funnel', 'performance'];
    if (cartesDuResume.some(c => this.voit(c))) {
      this.dashboardService.getRecruitmentSummary().subscribe({
        next: s => { this.summary = s; this.buildCharts(); this.isLoading = false; },
        error: () => { this.isLoading = false; },
      });
    } else {
      this.isLoading = false;
    }

    if (this.voit('education')) {
      this.dashboardService.getCandidateAnalytics().subscribe({
        next: a => { this.analytics = a; this.buildAnalytics(); },
        error: () => {},
      });
    }

    if (this.voit('evolution')) {
      this.dashboardService.getApplicationsTimeline(14).subscribe({
        next: t => { this.timeline = t; this.construireEvolutionSeries(); },
        error: () => {},
      });
    }
  }

  private buildFunnel(): void {
    const bs = this.summary?.applications_by_status;
    if (!bs) { this.funnel = []; return; }
    const total = this.summary?.total_applications
      || Object.values(bs).reduce((a, b) => a + (b as number), 0);
    const reviewed = total - (bs['PENDING'] || 0);
    const interview = (bs['INTERVIEW_SCHEDULED'] || 0) + (bs['NEGOTIATION'] || 0) + (bs['ACCEPTED'] || 0);
    const accepted = bs['ACCEPTED'] || 0;
    const stages = [
      { label: 'Candidatures reçues', count: total },
      { label: 'Examinées',           count: reviewed },
      { label: 'Entretien / négo',    count: interview },
      { label: 'Acceptées',           count: accepted },
    ];
    this.funnel = stages.map(s => ({ ...s, pct: total ? Math.round((s.count / total) * 100) : 0 }));
    this.construireFunnelSeries();
  }

  private withPct(items: LabelCount[]): Bar[] {
    const max = Math.max(1, ...items.map(i => i.count));
    return items.map(i => ({ ...i, pct: Math.round((i.count / max) * 100) }));
  }

  private buildAnalytics(): void {
    if (!this.analytics) return;
    this.eduBars = this.withPct(this.analytics.education);
    this.topSkills = this.analytics.top_skills;
  }

  private buildCharts(): void {
    if (!this.summary) return;

    const byStatus = this.summary.applications_by_status || {};
    const entries = Object.entries(byStatus).filter(([, v]) => (v as number) > 0);
    this.donutTotal = entries.reduce((sum, [, v]) => sum + (v as number), 0);

    let acc = 0;
    this.donut = entries.map(([key, v]) => {
      const val = v as number;
      const frac = this.donutTotal ? val / this.donutTotal : 0;
      const seg: DonutSeg = {
        key,
        label: this.statusMeta[key]?.label || key,
        value: val,
        color: this.statusMeta[key]?.color || '#A4B0B0',
        percent: Math.round(frac * 100),
        dash: `${(frac * this.C).toFixed(2)} ${(this.C - frac * this.C).toFixed(2)}`,
        offset: -(acc * this.C),
      };
      acc += frac;
      return seg;
    });

    const jobs = this.summary.top_jobs || [];
    const max = Math.max(1, ...jobs.map(j => j.application_count));
    this.topJobs = jobs.map(j => ({
      title: j.title,
      count: j.application_count,
      pct: Math.round((j.application_count / max) * 100),
    }));

    this.construireStatusSeries();
    this.construireJobsSeries();
    this.buildFunnel();
  }

  get acceptanceRate(): number { return this.summary?.acceptance_rate ?? 0; }
  get acceptanceDash(): string {
    const frac = this.acceptanceRate / 100;
    return `${(frac * this.C).toFixed(2)} ${(this.C - frac * this.C).toFixed(2)}`;
  }
  get averageScore(): number | null { return this.summary?.average_score ?? null; }

  statusLabel(s: string): string { return this.statusMeta[s]?.label || s; }
  statusColor(s: string): string { return this.statusMeta[s]?.color || '#A4B0B0'; }

  formatDate(d: string): string {
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
  }
  initials(name: string | null | undefined): string {
    if (!name) return '?';
    const p = name.trim().split(/\s+/);
    return ((p[0]?.[0] || '') + (p[1]?.[0] || '')).toUpperCase() || name.slice(0, 2).toUpperCase();
  }
  refresh(): void { this.load(); }

  // ── Séries pour app-chart, dérivées des données déjà calculées ──
  //
  // Des CHAMPS, pas des accesseurs (`get ... ()`). Un accesseur lu depuis le
  // gabarit (`*ngIf="evolutionSeries as s"`) est réévalué à CHAQUE cycle de
  // détection de changement d'Angular — bien plus souvent qu'à chaque vraie
  // mise à jour des données — et reconstruisait un objet neuf à chaque fois.
  // `app-chart` recevait donc une référence différente en permanence : son
  // `ngOnChanges` la voyait comme un changement réel et détruisait/recréait
  // le graphique Chart.js à chaque passage, d'où le clignotement — le
  // graphique qui « disparaît et s'affiche à chaque fois ». Calculée une
  // seule fois, au moment où la donnée source arrive, la référence reste
  // stable tant que rien n'a vraiment changé.
  evolutionSeries: ChartSeries | null = null;
  statusSeries: ChartSeries | null = null;
  jobsSeries: ChartSeries | null = null;
  funnelSeries: ChartSeries | null = null;

  private construireEvolutionSeries(): void {
    const s = this.timeline?.series;
    this.evolutionSeries = !s?.length ? null : {
      id: 'applications_timeline', label: 'Évolution des candidatures', kind: 'TEMPORELLE',
      points: s.map(p => ({ label: p.label, x: p.date, y: p.count })),
      allowed_types: this.evolutionTypes, default_type: 'area',
    };
  }

  private construireStatusSeries(): void {
    this.statusSeries = !this.donut.length ? null : {
      id: 'applications_by_status', label: 'Répartition des statuts', kind: 'CATEGORIELLE',
      points: this.donut.map(s => ({ label: s.label, x: s.key, y: s.value, color: s.color })),
      allowed_types: this.statusTypes, default_type: 'pie',
    };
  }

  private construireJobsSeries(): void {
    this.jobsSeries = !this.topJobs.length ? null : {
      id: 'applications_by_job', label: 'Candidatures par offre', kind: 'CATEGORIELLE',
      points: this.topJobs.map(j => ({ label: j.title, x: j.title, y: j.count })),
      allowed_types: this.jobsTypes, default_type: 'bar',
    };
  }

  private construireFunnelSeries(): void {
    this.funnelSeries = (!this.funnel.length || this.funnel[0].count <= 0) ? null : {
      id: 'recruitment_funnel', label: 'Pipeline de recrutement', kind: 'ORDONNEE',
      points: this.funnel.map(f => ({ label: f.label, x: f.label, y: f.count })),
      allowed_types: this.funnelTypes, default_type: 'bar',
    };
  }

  // ── Graphiques ajoutés par le RH ──

  private enGraphique(c: DashboardChart): GraphiquePersonnalise {
    return { id: c.id, sourceId: c.source_id, titre: c.title ?? null,
              type: c.chart_type, visibleTo: c.visible_to ?? 'ALL',
              serie: null, chargement: true, erreur: '',
              typeOptions: this.versOptions(
                this.catalogue.find(d => d.id === c.source_id)?.allowed_types
                ?? [c.chart_type]) };
  }

  /** Une source qui échoue ne doit pas emporter les autres cartes. */
  private chargerSerie(g: GraphiquePersonnalise): void {
    g.chargement = true;
    g.erreur = '';
    this.chartSeries.series(g.sourceId).subscribe({
      next: serie => {
        g.serie = serie;
        g.chargement = false;
        g.typeOptions = this.versOptions(serie.allowed_types ?? [g.type]);
      },
      error: () => { g.chargement = false; g.erreur = 'Cette source est indisponible.'; },
    });
  }

  titrePersonnalise(g: GraphiquePersonnalise): string {
    return g.titre || g.serie?.label
      || this.catalogue.find(d => d.id === g.sourceId)?.label || 'Graphique';
  }

  /** Pour un non-admin, la forme change à l'écran sans être enregistrée
   *  (`enregistrerComposition` ne fait rien sans le droit de modifier). */
  changerTypePersonnalise(g: GraphiquePersonnalise, type: ChartType): void {
    g.type = type;
    this.enregistrerComposition();
  }

  retirerGraphique(g: GraphiquePersonnalise): void {
    if (!this.peutModifier) return;
    this.graphiquesPersonnalises = this.graphiquesPersonnalises.filter(x => x !== g);
    this.enregistrerComposition();
  }

  /** Seul l'administrateur enregistre : la composition est commune à tous. */
  private enregistrerComposition(): void {
    if (!this.peutModifier) return;
    this.chartSeries.saveConfig({
      customized: true,
      builtin_visibility: this.visibiliteCartes,
      charts: this.graphiquesPersonnalises.map(g => ({
        id: g.id, source_id: g.sourceId, chart_type: g.type, title: g.titre, span: 6,
        visible_to: g.visibleTo,
      })),
    }).subscribe({ error: () => {} });
  }

  // ── Panneau « Créer un graphique » ──

  ouvrirPanneau(): void {
    if (!this.peutModifier) return;
    this.panneauOuvert = true;
    this.axeY = '';
    this.sourceChoisie = '';
    this.titreChoisi = '';
    this.audienceChoisie = 'ALL';
    this.previewSerie = null;
    this.rafraichirOptionsPanneau();
  }

  fermerPanneau(): void { this.panneauOuvert = false; }

  /** Les mesures disponibles, dans l'ordre d'apparition du catalogue. */
  get axesY(): string[] {
    return [...new Set(this.catalogue.map(d => d.y_label))];
  }

  /** Les répartitions possibles pour la mesure retenue. */
  get axesX(): SeriesDescriptor[] {
    return this.catalogue.filter(d => d.y_label === this.axeY);
  }

  /**
   * CES LISTES SONT DES CHAMPS, PAS DES GETTERS — et ce n'est pas un détail
   * de style.
   *
   * Un getter lié à `[options]` est réévalué à CHAQUE cycle de détection de
   * changement. Celui-ci rendait un tableau neuf, rempli d'objets neufs, à
   * chaque appel. Tant que la liste déroulante reste fermée, personne ne
   * compare ce tableau et l'inefficacité passe inaperçue. Dès que le
   * `*ngFor` de `app-select` le rend, le différentiel d'itérables voit des
   * identités neuves à chaque passe, redéclare la vue sale, et Angular
   * reboucle : mesuré à 189 000 évaluations pour UN clic, fil principal
   * bloqué, onglet figé.
   *
   * On recalcule donc au seul moment où la donnée change. Même raison que
   * pour les séries des graphiques (`construireStatusSeries` & co.).
   */
  axesYOptions: SelectOption[] = [];
  axesXOptions: SelectOption[] = [];
  typesDeLaSourceChoisieOptions: SelectOption[] = [];

  /** Recalcule les listes du panneau après un changement de catalogue/axe. */
  private rafraichirOptionsPanneau(): void {
    this.axesYOptions = this.axesY.map(y => ({ value: y, label: y }));
    this.axesXOptions = this.axesX.map(s => ({ value: s.id, label: s.x_label }));
    this.typesDeLaSourceChoisieOptions = this.versOptions(this.typesDeLaSourceChoisie);
  }

  surChoixAxeY(mesure: string): void {
    this.axeY = mesure;
    this.sourceChoisie = '';
    this.rafraichirOptionsPanneau();
    // Une seule répartition possible : la choisir d'office évite un clic qui
    // ne décide de rien.
    const possibles = this.axesX;
    if (possibles.length === 1) this.surChoixSource(possibles[0].id);
  }

  surChoixSource(id: string): void {
    this.sourceChoisie = id;
    // Le type par défaut de la source, pas le dernier choisi : une série
    // temporelle et un camembert n'ont pas les mêmes formes admissibles.
    this.typeChoisi = this.catalogue.find(d => d.id === id)?.default_type ?? 'bar';
    this.rafraichirOptionsPanneau();

    // L'aperçu montre la donnée RÉELLE plutôt qu'un nom de source dans une
    // liste — changer de forme ensuite (le sélecteur juste en dessous) rejoue
    // l'aperçu sans refaire cet appel, la donnée ne change pas avec la forme.
    this.previewSerie = null;
    this.previewChargement = true;
    this.chartSeries.series(id).subscribe({
      next: serie => { this.previewSerie = serie; this.previewChargement = false; },
      error: () => { this.previewChargement = false; },
    });
  }

  get typesDeLaSourceChoisie(): ChartType[] {
    return this.catalogue.find(d => d.id === this.sourceChoisie)?.allowed_types ?? [];
  }
  get sourceSelectionnee(): SeriesDescriptor | undefined {
    return this.catalogue.find(d => d.id === this.sourceChoisie);
  }

  /** {value, label} pour `app-select`, à partir d'une liste de formes. */
  versOptions(types: ChartType[]): SelectOption[] {
    return types.map(t => ({ value: t, label: CHART_TYPE_LABELS[t] }));
  }

  creerGraphique(): void {
    if (!this.sourceChoisie || !this.peutModifier) return;
    const g = this.enGraphique({
      id: `c${Date.now().toString(36)}`, source_id: this.sourceChoisie,
      chart_type: this.typeChoisi, title: this.titreChoisi.trim() || null, span: 6,
      visible_to: this.audienceChoisie,
    });
    this.graphiquesPersonnalises = [...this.graphiquesPersonnalises, g];
    this.chargerSerie(g);
    this.panneauOuvert = false;
    this.enregistrerComposition();
  }
}
