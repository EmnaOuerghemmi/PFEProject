import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  RecruitmentService, Application, applicationStatusLabel, isTerminalStatus, statusOptionsFor,
} from '../../../core/services/recruitment.service';
import { ContractService } from '../../../core/services/contract.service';
import { SafePipe } from '../../../core/pipes/safe.pipe';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';

type ApplicationDateFilter = 'recent' | 'oldest' | 'today' | 'week' | 'month';

@Component({
  selector: 'app-applications',
  standalone: true,
  imports: [CommonModule, FormsModule, SafePipe, SelectComponent],
  templateUrl: './applications.component.html',
  styleUrls: ['./applications.component.css']
})
export class ApplicationsComponent implements OnInit {
  private toast = inject(ToastService);
  private confirmService = inject(ConfirmService);

  applications: Application[] = [];
  filteredApplications: Application[] = [];
  paginatedApplications: Application[] = [];
  offerOptions: { id: string; title: string }[] = [];
  searchQuery = '';
  selectedOfferId = '';
  selectedDate: ApplicationDateFilter = 'recent';
  currentPage = 1;
  pageSize = 10;
  totalPages = 1;
  cvPreviewOpen = false;
  cvPreviewPath = '';
  generatingContract: string | null = null;

  constructor(
    private recruitment: RecruitmentService,
    private contracts: ContractService,
    private router: Router,
  ) {}

  /** Options par statut, calculées une fois (le template les relit à chaque cycle). */
  private readonly optionsCache = new Map<string, SelectOption[]>();
  readonly statusLabel = applicationStatusLabel;
  readonly isTerminal = isTerminalStatus;

  statusOptions(status: string): SelectOption[] {
    let options = this.optionsCache.get(status);
    if (!options) {
      options = statusOptionsFor(status).map(s => ({ value: s, label: applicationStatusLabel(s) }));
      this.optionsCache.set(status, options);
    }
    return options;
  }

  canGenerateContract(app: Application): boolean {
    return app.status === 'ACCEPTED' || app.status === 'NEGOTIATION';
  }

  generateContract(app: Application) {
    this.generatingContract = app.id;
    this.contracts.createFromApplication(app.id, { contract_type: 'CDI' }).subscribe({
      next: () => {
        this.generatingContract = null;
        this.router.navigate(['/admin/contracts']);
      },
      error: (err) => {
        this.generatingContract = null;
        this.toast.fromHttpError(err, 'Impossible de générer le contrat.');
        if (err?.status === 409) this.router.navigate(['/admin/contracts']);
      },
    });
  }

  ngOnInit() {
    this.loadApplications();
  }

  loadApplications() {
    this.recruitment.getApplications(undefined, 1, 100).subscribe({
      next: res => {
        this.applications = res;
        this.offerOptions = Array.from(
          new Map(
            res.map(app => [app.job_offer_id, app.job_offer_title || `#${app.job_offer_id.slice(0, 8)}`])
          )
        )
          .map(([id, title]) => ({ id, title }))
          .sort((first, second) => first.title.localeCompare(second.title, 'fr'));
        this.currentPage = 1;
        this.applyFilters();
      }
    });
  }

  applyFilters() {
    const query = this.searchQuery.trim().toLowerCase();

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const sevenDaysAgo = now.getTime() - 7 * 24 * 60 * 60 * 1000;
    const thirtyDaysAgo = now.getTime() - 30 * 24 * 60 * 60 * 1000;

    this.filteredApplications = this.applications.filter(app => {
      const candidate = app.candidate_name || app.candidate_id;
      const offer = app.job_offer_title || app.job_offer_id;
      const matchesQuery = !query || `${candidate} ${offer}`.toLowerCase().includes(query);
      const matchesOffer = !this.selectedOfferId || app.job_offer_id === this.selectedOfferId;
      const createdAt = new Date(app.created_at).getTime();
      const matchesDate = this.selectedDate === 'recent' || this.selectedDate === 'oldest'
        || (this.selectedDate === 'today' && createdAt >= todayStart)
        || (this.selectedDate === 'week' && createdAt >= sevenDaysAgo)
        || (this.selectedDate === 'month' && createdAt >= thirtyDaysAgo);
      return matchesQuery && matchesOffer && matchesDate;
    }).sort((first, second) => {
      const firstDate = new Date(first.created_at).getTime();
      const secondDate = new Date(second.created_at).getTime();
      return this.selectedDate === 'oldest' ? firstDate - secondDate : secondDate - firstDate;
    });

    this.currentPage = 1;
    this.updatePagination();
  }

  resetFilters() {
    this.searchQuery = '';
    this.selectedOfferId = '';
    this.selectedDate = 'recent';
    this.applyFilters();
  }

  hasActiveFilters(): boolean {
    return Boolean(this.searchQuery || this.selectedOfferId || this.selectedDate !== 'recent');
  }

  updatePagination() {
    this.totalPages = Math.max(1, Math.ceil(this.filteredApplications.length / this.pageSize));
    const start = (this.currentPage - 1) * this.pageSize;
    this.paginatedApplications = this.filteredApplications.slice(start, start + this.pageSize);
  }

  goToPage(page: number) {
    this.currentPage = page;
    this.updatePagination();
  }

  onPageSizeChange(newSize: number) {
    this.pageSize = newSize;
    this.currentPage = 1;
    this.updatePagination();
  }

  updateStatus(app: Application, status: string) {
    if (status === app.status) return;
    this.recruitment.updateApplication(app.id, status).subscribe({
      next: () => this.loadApplications(),
      // Transition refusée : on recharge, les lignes sont recréées et le
      // sélecteur revient au statut réel plutôt qu'à une valeur non enregistrée.
      error: err => {
        this.toast.fromHttpError(err, 'Changement de statut refusé.');
        this.loadApplications();
      }
    });
  }

  async deleteApp(appId: string) {
    const ok = await this.confirmService.askDelete(
      'Supprimer définitivement cette candidature et son CV ? Cette action est irréversible.'
    );
    if (ok) {
      this.recruitment.deleteApplication(appId).subscribe({
        next: () => this.loadApplications(),
        error: err => this.toast.fromHttpError(err, 'Suppression impossible — réservée aux administrateurs.')
      });
    }
  }

  exportCsv() {
    this.recruitment.exportApplications().subscribe({
      next: blob => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'candidatures.csv';
        link.click();
        URL.revokeObjectURL(url);
      },
      error: err => this.toast.fromHttpError(err, "L'export a échoué.")
    });
  }

  getCVDownloadUrl(cvPath: string): string {
    return this.recruitment.getCVDownloadUrl(cvPath);
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
