import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  RecruitmentService, JobOffer,
  WORK_MODE_LABELS, CONTRACT_TYPE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { PaginationComponent } from '../../../shared/components/pagination/pagination.component';

@Component({
  selector: 'app-job-list',
  standalone: true,
  imports: [CommonModule, FormsModule, PaginationComponent],
  templateUrl: './job-list.component.html',
  styleUrls: ['./job-list.component.css']
})
export class JobListComponent implements OnInit {
  jobs: JobOffer[] = [];
  filteredJobs: JobOffer[] = [];
  paginatedJobs: JobOffer[] = [];

  searchQuery = '';
  sortBy = 'newest';
  totalItems = 0;
  currentPage = 1;
  pageSize = 10;
  totalPages = 1;

  experienceFilter = '';
  educationFilter = '';
  salaryFilter = '';
  sidebarOpen = false;

  readonly sortOptions = [
    { value: 'newest', label: 'Plus récentes' },
    { value: 'oldest', label: 'Plus anciennes' },
    { value: 'title',  label: 'Titre A–Z' },
  ];

  readonly expOptions = [
    { value: '',    label: 'Tous niveaux' },
    { value: '0-2', label: '0 – 2 ans' },
    { value: '2-5', label: '2 – 5 ans' },
    { value: '5+',  label: '5 ans et plus' },
  ];

  readonly eduOptions = [
    { value: '',         label: 'Tous niveaux' },
    { value: 'bac',      label: 'Bac' },
    { value: 'bac+2',    label: 'Bac+2' },
    { value: 'licence',  label: 'Licence (Bac+3)' },
    { value: 'master',   label: 'Master (Bac+5)' },
    { value: 'doctorat', label: 'Doctorat' },
  ];

  readonly salaryOptions = [
    { value: '',     label: 'Tous salaires' },
    { value: '1000', label: '1 000+ TND' },
    { value: '2000', label: '2 000+ TND' },
    { value: '3000', label: '3 000+ TND' },
    { value: '5000', label: '5 000+ TND' },
  ];

  constructor(private recruitment: RecruitmentService, private router: Router) {}

  ngOnInit() { this.loadJobs(); }

  loadJobs() {
    this.recruitment.getJobs(this.currentPage, this.pageSize, this.searchQuery.trim(), this.sortBy).subscribe({
      next: res => {
        this.jobs = res.items;
        this.totalItems = res.total;
        this.totalPages = Math.max(1, Math.ceil(res.total / this.pageSize));
        this.applyLocalFilters();
      }
    });
  }

  applyLocalFilters() {
    let list = [...this.jobs];

    if (this.experienceFilter) {
      const [min, max] = this.getExpRange(this.experienceFilter);
      list = list.filter(j => {
        const exp = j.required_experience_years ?? 0;
        return exp >= min && (max === null || exp <= max);
      });
    }

    if (this.educationFilter) {
      list = list.filter(j =>
        j.required_education_level?.toLowerCase().includes(this.educationFilter)
      );
    }

    if (this.salaryFilter) {
      const minSal = parseInt(this.salaryFilter, 10);
      list = list.filter(j => (j.salary_min ?? 0) >= minSal);
    }

    this.filteredJobs = list;
    this.paginatedJobs = list;
  }

  private getExpRange(f: string): [number, number | null] {
    if (f === '0-2') return [0, 2];
    if (f === '2-5') return [2, 5];
    if (f === '5+')  return [5, null];
    return [0, null];
  }

  applyFilters() { this.currentPage = 1; this.loadJobs(); }
  applyLocalOnly() { this.applyLocalFilters(); }

  goToPage(page: number) {
    this.currentPage = page;
    this.loadJobs();
    window.scrollTo(0, 0);
  }

  onPageSizeChange(size: number) {
    this.pageSize = size;
    this.currentPage = 1;
    this.loadJobs();
  }

  resetFilters() {
    this.searchQuery = '';
    this.sortBy = 'newest';
    this.experienceFilter = '';
    this.educationFilter = '';
    this.salaryFilter = '';
    this.currentPage = 1;
    this.pageSize = 10;
    this.loadJobs();
  }

  viewJob(id: string) { this.router.navigate(['/frontoffice/job', id]); }

  getShortDescription(desc: string): string {
    if (!desc) return '';
    return desc.length > 155 ? desc.slice(0, 155) + '…' : desc;
  }

  getDaysAgo(dateStr: string): string {
    const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000);
    if (diff === 0) return "Aujourd'hui";
    if (diff === 1) return 'Hier';
    if (diff < 7)  return `Il y a ${diff}j`;
    if (diff < 30) return `Il y a ${Math.floor(diff / 7)} sem.`;
    return `Il y a ${Math.floor(diff / 30)} mois`;
  }

  workModeLabel(job: JobOffer): string {
    return job.work_mode ? WORK_MODE_LABELS[job.work_mode] : '';
  }

  contractTypeLabel(job: JobOffer): string {
    return contractTypesLabel(job.contract_types);
  }

  getActiveFiltersCount(): number {
    let n = 0;
    if (this.searchQuery)           n++;
    if (this.sortBy !== 'newest')   n++;
    if (this.experienceFilter)      n++;
    if (this.educationFilter)       n++;
    if (this.salaryFilter)          n++;
    return n;
  }

  hasActiveFilters(): boolean { return this.getActiveFiltersCount() > 0; }
  toggleSidebar() { this.sidebarOpen = !this.sidebarOpen; }

  quickSearch(term: string) {
    this.searchQuery = term;
    this.applyFilters();
  }
}
