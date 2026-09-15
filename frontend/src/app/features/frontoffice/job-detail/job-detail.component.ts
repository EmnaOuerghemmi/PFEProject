import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Observable } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import {
  RecruitmentService, JobOffer,
  WORK_MODE_LABELS, CONTRACT_TYPE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { AuthService } from '../../../core/services/auth.service';
import { ApplyModalComponent } from '../../../shared/components/apply-modal/apply-modal.component';

@Component({
  selector: 'app-job-detail',
  standalone: true,
  imports: [CommonModule, ApplyModalComponent],
  templateUrl: './job-detail.component.html',
  styleUrls: ['./job-detail.component.css']
})
export class JobDetailComponent implements OnInit {
  job: JobOffer | null = null;
  isApplying = false;
  successMsg = '';
  errorMsg = '';
  selectedFile: File | null = null;
  analysisData: any = null;
  cvAnalysisData: any = null;
  currentApplicationId: string | null = null;
  isSaved = false;
  saving = false;

  /** Modale de candidature (choix du CV, puis prétention salariale). */
  modaleOuverte = false;

  get isAuthenticated(): boolean {
    return this.auth.isAuthenticated();
  }

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private recruitment: RecruitmentService,
    private auth: AuthService
  ) {}

  ngOnInit() {
    const jobId = this.route.snapshot.paramMap.get('id');
    if (jobId) {
      this.recruitment.getJob(jobId).subscribe({
        next: job => this.job = job,
        error: () => this.router.navigate(['/frontoffice/jobs'])
      });
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      const allowedTypes = ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
      const allowedExt = ['.pdf', '.doc', '.docx'];
      const maxSize = 5 * 1024 * 1024;
      const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();

      // Some browsers report an empty MIME for .docx — fall back to extension.
      if (!allowedTypes.includes(file.type) && !allowedExt.includes(ext)) {
        this.errorMsg = 'Seuls les formats PDF, DOC et DOCX sont acceptés.';
        this.selectedFile = null;
        console.error('❌ File type not allowed:', file.type, ext);
        return;
      }

      if (file.size > maxSize) {
        this.errorMsg = 'La taille du fichier ne doit pas dépasser 5 MB';
        this.selectedFile = null;
        console.error('❌ File too large:', file.size);
        return;
      }

      this.selectedFile = file;
      this.errorMsg = '';
    } else {
    }
  }

  ouvrirModale(): void {
    if (!this.job) return;
    this.errorMsg = '';
    this.successMsg = '';
    this.modaleOuverte = true;
  }

  fermerModale(): void {
    this.modaleOuverte = false;
  }

  /**
   * La modale signale que la candidature est ENREGISTRÉE — avant même que le
   * candidat ait répondu à la question du salaire, qui est facultative. On met
   * donc l'écran à jour dès maintenant.
   */
  surCandidatureEnvoyee(): void {
    this.successMsg = 'Candidature envoyée. Votre dossier est en cours de traitement.';
    this.selectedFile = null;
  }

  toggleSave() {
    if (!this.job || this.saving) return;
    this.saving = true;
    const req: Observable<unknown> = this.isSaved
      ? this.recruitment.unsaveJob(this.job.id)
      : this.recruitment.saveJob(this.job.id);
    req.subscribe({
      next: () => { this.isSaved = !this.isSaved; this.saving = false; },
      error: (err: any) => { this.saving = false; this.errorMsg = err.error?.detail || 'Action impossible.'; },
    });
  }

  goBack() {
    this.router.navigate(['/frontoffice/jobs']);
  }

  goLogin() {
    this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
  }

  getEducationLabel(level: string): string {
    const labels: Record<string, string> = {
      'HIGH_SCHOOL': 'Baccalauréat',
      'BACHELOR': 'Licence',
      'INGENIEUR': 'Ingénieur',
      'MASTER': 'Master',
      'PhD': 'Doctorat'
    };
    return labels[level] || level;
  }

  workModeLabel(job: JobOffer): string {
    return job.work_mode ? WORK_MODE_LABELS[job.work_mode] : '';
  }

  contractTypeLabel(job: JobOffer): string {
    return contractTypesLabel(job.contract_types);
  }

  /** Date limite dépassée → le backend refusera la candidature, on la bloque en amont. */
  isExpired(job: JobOffer): boolean {
    return !!job.expires_at && new Date(job.expires_at).getTime() < Date.now();
  }
}
