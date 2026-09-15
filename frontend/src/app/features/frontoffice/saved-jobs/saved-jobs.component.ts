import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import {
  RecruitmentService, JobOffer,
  WORK_MODE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'app-saved-jobs',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './saved-jobs.component.html',
  styleUrls: ['./saved-jobs.component.css']
})
export class SavedJobsComponent implements OnInit {
  private toast = inject(ToastService);

  savedJobs: JobOffer[] = [];
  loading = false;
  errorMsg = '';

  constructor(private recruitment: RecruitmentService, private router: Router) {}

  ngOnInit(): void {
    this.loadSavedJobs();
  }

  loadSavedJobs(): void {
    this.loading = true;
    this.recruitment.getSavedJobs().subscribe({
      next: jobs => {
        this.savedJobs = jobs;
        this.loading = false;
      },
      error: err => {
        this.errorMsg = err.error?.detail || 'Impossible de charger vos offres sauvegardées.';
        this.loading = false;
      },
    });
  }

  removeSaved(job: JobOffer): void {
    this.recruitment.unsaveJob(job.id).subscribe({
      next: () => this.savedJobs = this.savedJobs.filter(j => j.id !== job.id),
      error: err => this.toast.fromHttpError(err, 'Impossible de retirer cette offre.'),
    });
  }

  workModeLabel(job: JobOffer): string {
    return job.work_mode ? WORK_MODE_LABELS[job.work_mode] : '';
  }

  contractTypeLabel(job: JobOffer): string {
    return contractTypesLabel(job.contract_types);
  }

  applyJob(jobId: string): void {
    this.router.navigate(['/frontoffice/job', jobId]);
  }
}
