import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DashboardService } from '../services/dashboard.service';
import { AuthService } from '../../../core/services/auth.service';
import { RecruitmentService, RecruitmentSummary, CandidateAnalytics, LabelCount, ApplicationsTimeline } from '../../../core/services/recruitment.service';
import { APPLICATION_STATUS_META } from '../../../core/services/recruitment.service';
import { CustomChartsComponent } from './custom-charts.component';

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
  imports: [CommonModule, CustomChartsComponent],
  templateUrl: './backoffice-dashboard.component.html',
  styleUrls: ['./backoffice-dashboard.component.css'],
})
export class BackofficeDashboardComponent implements OnInit {
  stats = { totalJobs: 0, totalApplications: 0, totalHires: 0, activeUsers: 0, newUsers: 0 };
  summary: RecruitmentSummary | null = null;
  analytics: CandidateAnalytics | null = null;
  isSuperAdmin = false;
  isLoading = true;

  // Candidate analytics (bar charts)
  expBars: Bar[] = [];
  scoreBars: Bar[] = [];
  eduBars: Bar[] = [];
  topSkills: LabelCount[] = [];

  // Evolution (area/line) chart
  timeline: ApplicationsTimeline | null = null;
  readonly TLW = 600;
  readonly TLH = 150;
  linePts = '';
  areaPath = '';
  tlMax = 0;

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

  constructor(
    private dashboardService: DashboardService,
    private authService: AuthService,
    private recruitment: RecruitmentService,
  ) {}

  ngOnInit(): void {
    this.isSuperAdmin = this.authService.getCurrentUser()?.is_superuser || false;
    this.load();
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

    this.recruitment.getRecruitmentSummary().subscribe({
      next: s => { this.summary = s; this.buildCharts(); this.isLoading = false; },
      error: () => { this.isLoading = false; },
    });

    this.recruitment.getCandidateAnalytics().subscribe({
      next: a => { this.analytics = a; this.buildAnalytics(); },
      error: () => {},
    });

    this.recruitment.getApplicationsTimeline(14).subscribe({
      next: t => { this.timeline = t; this.buildTimeline(); },
      error: () => {},
    });
  }

  private buildTimeline(): void {
    const s = this.timeline?.series || [];
    if (!s.length) { this.linePts = ''; this.areaPath = ''; return; }
    const max = Math.max(1, ...s.map(p => p.count));
    this.tlMax = max;
    const w = this.TLW, h = this.TLH, pad = 18;
    const stepX = s.length > 1 ? w / (s.length - 1) : 0;
    const pts = s.map((p, i) => {
      const x = i * stepX;
      const y = h - pad - (p.count / max) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    this.linePts = pts.join(' ');
    this.areaPath = `M0,${h} L` + pts.join(' L') + ` L${w},${h} Z`;
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
  }

  private withPct(items: LabelCount[]): Bar[] {
    const max = Math.max(1, ...items.map(i => i.count));
    return items.map(i => ({ ...i, pct: Math.round((i.count / max) * 100) }));
  }

  private buildAnalytics(): void {
    if (!this.analytics) return;
    this.expBars = this.withPct(this.analytics.experience_buckets);
    this.scoreBars = this.withPct(this.analytics.score_bands);
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
}
