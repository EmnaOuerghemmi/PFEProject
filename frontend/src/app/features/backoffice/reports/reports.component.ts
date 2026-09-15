import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PaginationComponent } from '../../../shared/components/pagination/pagination.component';
import {
  ReportService, RecruitmentSummary, ReportSnapshot, PaginatedReports,
} from '../../../core/services/report.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { APPLICATION_STATUSES, applicationStatusLabel } from '../../../core/services/recruitment.service';

@Component({
  selector: 'app-reports',
  standalone: true,
  imports: [CommonModule, FormsModule, PaginationComponent],
  templateUrl: './reports.component.html',
  styleUrls: ['./reports.component.css'],
})
export class ReportsComponent implements OnInit {
  private confirmService = inject(ConfirmService);

  // Résumé live
  summary: RecruitmentSummary | null = null;

  // Liste paginée
  reports: ReportSnapshot[] = [];
  total = 0;
  page = 1;
  pages = 1;
  pageSize = 10;
  loading = true;
  error = '';

  // Génération
  newTitle = '';
  generating = false;

  // Détail / renommage
  expandedId: string | null = null;
  renamingId: string | null = null;
  renameValue = '';
  downloadingId: string | null = null;

  constructor(private reportService: ReportService) {}

  ngOnInit(): void {
    this.loadSummary();
    this.loadReports();
  }

  loadSummary(): void {
    this.reportService.getSummary().subscribe({
      next: (s) => (this.summary = s),
    });
  }

  loadReports(): void {
    this.loading = true;
    this.error = '';
    this.reportService.listReports(this.page, this.pageSize).subscribe({
      next: (res: PaginatedReports) => {
        this.reports = res.items;
        this.total = res.total;
        this.pages = res.pages;
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail || 'Impossible de charger les rapports.';
      },
    });
  }

  onPageChange(p: number): void {
    this.page = p;
    this.expandedId = null;
    this.loadReports();
  }

  onPageSizeChange(size: number): void {
    this.pageSize = size;
    this.page = 1;
    this.loadReports();
  }

  // ── Génération (agent IA) ──────────────────────────────────────────────────

  generate(): void {
    this.generating = true;
    this.error = '';
    this.reportService.generateReport(this.newTitle.trim() || undefined).subscribe({
      next: (snap) => {
        this.generating = false;
        this.newTitle = '';
        this.page = 1;
        this.loadReports();
        this.expandedId = snap.id; // ouvrir directement le rapport généré
      },
      error: (err) => {
        this.generating = false;
        this.error = err?.error?.detail || 'La génération du rapport a échoué.';
      },
    });
  }

  // ── Actions par rapport ────────────────────────────────────────────────────

  toggleDetail(r: ReportSnapshot): void {
    this.expandedId = this.expandedId === r.id ? null : r.id;
    this.renamingId = null;
  }

  startRename(r: ReportSnapshot, event: Event): void {
    event.stopPropagation();
    this.renamingId = r.id;
    this.renameValue = r.title || '';
  }

  confirmRename(r: ReportSnapshot, event: Event): void {
    event.stopPropagation();
    const title = this.renameValue.trim();
    if (!title) { this.renamingId = null; return; }
    this.reportService.renameReport(r.id, title).subscribe({
      next: (updated) => {
        r.title = updated.title;
        this.renamingId = null;
      },
      error: () => { this.renamingId = null; },
    });
  }

  cancelRename(event: Event): void {
    event.stopPropagation();
    this.renamingId = null;
  }

  downloadPdf(r: ReportSnapshot, event: Event): void {
    event.stopPropagation();
    this.downloadingId = r.id;
    this.reportService.downloadPdf(r.id).subscribe({
      next: (blob) => {
        this.downloadingId = null;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `PIQBIT_${(r.title || 'rapport').replace(/\s+/g, '_')}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      },
      error: () => {
        this.downloadingId = null;
        this.error = 'Téléchargement PDF impossible.';
      },
    });
  }

  async remove(r: ReportSnapshot, event: Event): Promise<void> {
    event.stopPropagation();
    const ok = await this.confirmService.askDelete(`Supprimer le rapport « ${r.title} » ?`);
    if (!ok) return;
    this.reportService.deleteReport(r.id).subscribe({
      next: () => {
        if (this.reports.length === 1 && this.page > 1) this.page--;
        this.loadReports();
      },
      error: () => { this.error = 'Suppression impossible.'; },
    });
  }

  // ── Helpers d'affichage ────────────────────────────────────────────────────

  statusEntries(r: ReportSnapshot): { label: string; count: number }[] {
    // Dérivé de la table partagée : cette liste locale omettait les statuts de
    // test et les embauchés, dont le rapport ne parlait donc jamais.
    const by = r.data?.applications_by_status || {};
    return APPLICATION_STATUSES.map((k) => ({
      label: applicationStatusLabel(k),
      count: (by as any)[k] || 0,
    }));
  }

  trackReport(_i: number, r: ReportSnapshot): string { return r.id; }
}
