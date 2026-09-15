import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import {
  RecruitmentService, MyApplication,
  WORK_MODE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { SafePipe } from '../../../core/pipes/safe.pipe';
import { PaginationComponent } from '../../../shared/components/pagination/pagination.component';
import { ToastService } from '../../../core/services/toast.service';

type StatusFilter = '' | 'PENDING' | 'REVIEWED' | 'ACCEPTED' | 'REJECTED';

@Component({
  selector: 'app-my-applications',
  standalone: true,
  imports: [CommonModule, FormsModule, SafePipe, RouterModule, PaginationComponent],
  templateUrl: './my-applications.component.html',
  styleUrls: ['./my-applications.component.css']
})
export class MyApplicationsComponent implements OnInit {
  private toast = inject(ToastService);

  applications: MyApplication[] = [];
  filtered: MyApplication[] = [];
  paginated: MyApplication[] = [];

  // Filters
  searchQuery = '';
  statusFilter: StatusFilter = '';
  sortBy: 'newest' | 'oldest' | 'score' = 'newest';

  // CV preview modal
  cvPreviewOpen = false;
  cvPreviewPath = '';

  // Loading & error
  isLoading = false;
  errorMsg = '';

  // Pagination
  currentPage = 1;
  pageSize = 9;
  totalPages = 1;

  readonly statusOptions: { value: StatusFilter; label: string }[] = [
    { value: '',         label: 'Tous les statuts' },
    { value: 'PENDING',  label: 'En attente' },
    { value: 'REVIEWED', label: 'Examinées' },
    { value: 'ACCEPTED', label: 'Acceptées' },
    { value: 'REJECTED', label: 'Rejetées' },
  ];

  readonly sortOptions: { value: 'newest' | 'oldest' | 'score'; label: string }[] = [
    { value: 'newest', label: 'Plus récentes' },
    { value: 'oldest', label: 'Plus anciennes' },
    { value: 'score',  label: 'Meilleur score' },
  ];

  constructor(private recruitment: RecruitmentService, private router: Router) {}

  ngOnInit() {
    this.loadApplications();
  }

  loadApplications() {
    this.isLoading = true;
    this.errorMsg = '';
    this.recruitment.getMyApplications().subscribe({
      next: res => {
        this.applications = res;
        this.applyFilters();
        this.isLoading = false;
      },
      error: err => {
        this.applications = [];
        this.filtered = [];
        this.paginated = [];
        this.isLoading = false;
        this.errorMsg = err?.error?.detail || 'Impossible de charger vos candidatures.';
      }
    });
  }

  // ── FILTERS ─────────────────────────────────────────────
  applyFilters() {
    const q = this.searchQuery.trim().toLowerCase();
    let list = this.applications.filter(app => {
      if (this.statusFilter && app.status !== this.statusFilter) return false;
      if (!q) return true;
      const haystack = [
        app.job_title,
        app.job_description,
        ...(app.job_required_skills || [])
      ].join(' ').toLowerCase();
      return haystack.includes(q);
    });

    if (this.sortBy === 'oldest') {
      list = list.sort((a, b) => +new Date(a.created_at) - +new Date(b.created_at));
    } else if (this.sortBy === 'score') {
      list = list.sort((a, b) => (b.total_score ?? -1) - (a.total_score ?? -1));
    } else {
      list = list.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
    }

    this.filtered = list;
    this.currentPage = 1;
    this.updatePagination();
  }

  resetFilters() {
    this.searchQuery = '';
    this.statusFilter = '';
    this.sortBy = 'newest';
    this.applyFilters();
  }

  hasActiveFilters(): boolean {
    return this.searchQuery.length > 0 || this.statusFilter !== '' || this.sortBy !== 'newest';
  }

  // ── PAGINATION ─────────────────────────────────────────
  updatePagination() {
    this.totalPages = Math.max(1, Math.ceil(this.filtered.length / this.pageSize));
    const start = (this.currentPage - 1) * this.pageSize;
    this.paginated = this.filtered.slice(start, start + this.pageSize);
  }

  goToPage(page: number) {
    this.currentPage = page;
    this.updatePagination();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onPageSizeChange(newSize: number) {
    this.pageSize = newSize;
    this.currentPage = 1;
    this.updatePagination();
  }

  // ── STATUS HELPERS ─────────────────────────────────────
  getStatusLabel(status: string): string {
    const labels: { [key: string]: string } = {
      'PENDING':  'En attente',
      'REVIEWED': 'Examinée',
      'ACCEPTED': 'Acceptée',
      'REJECTED': 'Rejetée'
    };
    return labels[status] || status;
  }

  getStatusCount(status: string): number {
    return this.applications.filter(a => a.status === status).length;
  }

  // ── TIME HELPERS ───────────────────────────────────────
  workModeLabel(app: MyApplication): string {
    return app.job_work_mode ? WORK_MODE_LABELS[app.job_work_mode] : '';
  }

  contractTypeLabel(app: MyApplication): string {
    return contractTypesLabel(app.job_contract_types);
  }

  getDaysAgo(dateStr: string): string {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    if (days <= 0) return "Aujourd'hui";
    if (days === 1) return 'Hier';
    if (days < 7)   return `Il y a ${days} jours`;
    if (days < 30)  return `Il y a ${Math.floor(days / 7)} sem.`;
    if (days < 365) return `Il y a ${Math.floor(days / 30)} mois`;
    return `Il y a ${Math.floor(days / 365)} an${days >= 730 ? 's' : ''}`;
  }

  // ── SCORE HELPERS ──────────────────────────────────────
  getScoreTone(score: number | null): 'excellent' | 'good' | 'average' | 'poor' | 'none' {
    if (score === null || score === undefined) return 'none';
    if (score >= 85) return 'excellent';
    if (score >= 60) return 'good';
    if (score >= 30) return 'average';
    return 'poor';
  }

  // ── ACTIONS ────────────────────────────────────────────
  viewJob(jobId: string) {
    this.router.navigate(['/jobs', jobId]);
  }

  downloadCV(cvPath: string) {
    this.recruitment.downloadCVAsBlob(cvPath).subscribe({
      next: blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cv_${new Date().getTime()}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      },
      error: err => this.toast.fromHttpError(err, 'Le téléchargement du CV a échoué.')
    });
  }

  openCVPreview(cvPath: string) {
    this.recruitment.downloadCVAsBlob(cvPath).subscribe({
      next: blob => {
        const url = URL.createObjectURL(blob);
        this.cvPreviewPath = url;
        this.cvPreviewOpen = true;
      },
      error: err => this.toast.fromHttpError(err, 'Impossible de charger le CV.')
    });
  }

  closeCVPreview() {
    if (this.cvPreviewPath.startsWith('blob:')) {
      URL.revokeObjectURL(this.cvPreviewPath);
    }
    this.cvPreviewOpen = false;
    this.cvPreviewPath = '';
  }
}
