import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import {
  RecruitmentService, JobOffer,
  WORK_MODE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'app-saved-jobs',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './saved-jobs.component.html',
  styleUrls: ['./saved-jobs.component.css'],
})
export class SavedJobsComponent implements OnInit {
  private toast  = inject(ToastService);
  private recruitment = inject(RecruitmentService);
  private router = inject(Router);

  savedJobs: JobOffer[] = [];
  isLoading  = false;
  errorMsg   = '';
  searchQuery = '';

  ngOnInit(): void { this.loadSavedJobs(); }

  loadSavedJobs(): void {
    this.isLoading = true;
    this.errorMsg  = '';
    this.recruitment.getSavedJobs().subscribe({
      next: jobs => { this.savedJobs = jobs; this.isLoading = false; },
      error: err  => {
        this.errorMsg = err.error?.detail || 'Impossible de charger vos offres sauvegardées.';
        this.isLoading = false;
      },
    });
  }

  get withDeadline(): number {
    return this.savedJobs.filter(j => j.expires_at).length;
  }

  get filtered(): JobOffer[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.savedJobs;
    return this.savedJobs.filter(j =>
      j.title.toLowerCase().includes(q) ||
      (j.description || '').toLowerCase().includes(q) ||
      (j.required_skills || []).some(s => s.toLowerCase().includes(q))
    );
  }

  removeSaved(job: JobOffer, event: Event): void {
    event.stopPropagation();
    this.recruitment.unsaveJob(job.id).subscribe({
      next: () => {
        this.savedJobs = this.savedJobs.filter(j => j.id !== job.id);
        this.toast.success('Offre retirée des favoris.');
      },
      error: err => this.toast.fromHttpError(err, 'Impossible de retirer cette offre.'),
    });
  }

  viewJob(jobId: string, event?: Event): void {
    event?.stopPropagation();
    this.router.navigate(['/frontoffice/job', jobId]);
  }

  workModeLabel(job: JobOffer): string {
    return job.work_mode ? WORK_MODE_LABELS[job.work_mode] : '';
  }

  contractTypeLabel(job: JobOffer): string {
    return contractTypesLabel(job.contract_types);
  }

  getDaysAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return "Aujourd'hui";
    if (days === 1) return 'Il y a 1 jour';
    if (days < 7)  return `Il y a ${days} jours`;
    const weeks = Math.floor(days / 7);
    if (weeks === 1) return 'Il y a 1 sem.';
    if (weeks < 5)  return `Il y a ${weeks} sem.`;
    const months = Math.floor(days / 30);
    return months <= 1 ? 'Il y a 1 mois' : `Il y a ${months} mois`;
  }

  trackById(_: number, job: JobOffer): string { return job.id; }
}
