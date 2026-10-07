import { Component, HostListener, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  RecruitmentService, JobOffer, Application,
  SalarySuggestion, NegotiationChatMessage, JobExtractionResponse,
  WorkMode, ContractType, JobStatus,
  WORK_MODE_LABELS, CONTRACT_TYPE_LABELS, JOB_STATUS_LABELS, contractTypesLabel,
  APPLICATION_STATUSES, applicationStatusLabel, isTerminalStatus, statusOptionsFor,
} from '../../../core/services/recruitment.service';
import { SafePipe } from '../../../core/pipes/safe.pipe';
import { PaginationComponent } from '../../../shared/components/pagination/pagination.component';
import { CandidateRankingComponent, WorkflowAction } from '../../../shared/components/candidate-ranking/candidate-ranking.component';
import { ScoreBreakdownComponent } from '../../../shared/components/score-breakdown/score-breakdown.component';
import { CVAnalysisComponent } from '../../../shared/components/cv-analysis/cv-analysis.component';
import { InterviewSchedulerComponent } from '../../../shared/components/interview-scheduler/interview-scheduler.component';
import { TECH_SKILLS } from '../../../shared/constants/tech-skills';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { PermissionsService } from '../../../core/services/permissions.service';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';

@Component({
  selector: 'app-jobs-management',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SelectComponent,
    SafePipe,
    PaginationComponent,
    CandidateRankingComponent,
    ScoreBreakdownComponent,
    CVAnalysisComponent,
    InterviewSchedulerComponent,
  ],
  templateUrl: './jobs-management.component.html',
  styleUrls: [
    './jobs-management.component.css',
    // Re-skin ::ng-deep des composants partagés rendus dans la modale
    // candidats. Doit rester en SECOND : plusieurs de ses règles
    // l'emportent par l'ordre source, à spécificité égale.
    './jobs-management.overrides.css',
  ]
})
export class JobsManagementComponent implements OnInit {
  private toast = inject(ToastService);
  private confirmService = inject(ConfirmService);
  private permissions = inject(PermissionsService);

  /**
   * Créer, modifier, activer/désactiver une offre : `jobs:write` (RH, admin).
   * Supprimer : `jobs:delete`. Le recruteur n'a que `jobs:read` — il consulte
   * les offres et traite leurs candidatures, sans toucher aux offres. Le
   * serveur refuse de toute façon ; masquer les boutons évite d'en proposer
   * qui échoueraient.
   */
  get peutModifierOffres(): boolean { return this.permissions.peut('jobs', 'write'); }
  get peutSupprimerOffres(): boolean { return this.permissions.peut('jobs', 'delete'); }

  jobs: JobOffer[] = [];
  filteredJobs: JobOffer[] = [];
  searchTerm = '';
  sortBy = '';
  statusFilter = '';
  jobsLoading = false;
  savingJob = false;
  drawerOpen = false;
  editingJob: JobOffer | null = null;
  /** Formulaire vierge — une seule définition, réutilisée à l'ouverture et à la fermeture. */
  private static emptyForm() {
    return {
      title: '',
      description: '',
      salary_min: null as number | null,
      salary_max: null as number | null,
      required_skills: [] as string[],
      required_experience_years: null as number | null,
      required_education_level: '',
      weight_skills: 0.5,
      weight_experience: 0.3,
      weight_education: 0.2,
      work_mode: '' as WorkMode | '',
      contract_types: [] as ContractType[],
      status: 'PUBLISHED' as JobStatus,
      /** `<input type="datetime-local">` travaille en 'YYYY-MM-DDTHH:mm'. */
      expires_at: '' as string,
    };
  }

  formData = JobsManagementComponent.emptyForm();

  readonly workModes: WorkMode[] = ['ON_SITE', 'HYBRID', 'REMOTE'];
  readonly contractTypes: ContractType[] = ['CDI', 'CDD', 'SIVP', 'STAGE', 'FREELANCE'];
  readonly jobStatuses: JobStatus[] = ['DRAFT', 'PUBLISHED', 'CLOSED'];

  /**
   * Des CHAMPS, pas des getters. Un `[options]` alimenté par un getter est
   * réévalué à chaque cycle de détection et rend un tableau neuf : le
   * différentiel de `*ngFor` ne converge alors jamais et l'onglet se fige
   * (mesuré sur le tableau de bord). La première entrée, à valeur vide, sert
   * de remise à zéro — comme le faisait la première <option> du select natif.
   */
  readonly triOptions: SelectOption[] = [
    { value: '',       label: 'Trier par…' },
    { value: 'newest', label: 'Plus récents' },
    { value: 'oldest', label: 'Plus anciens' },
    { value: 'title',  label: 'Titre (A-Z)' },
  ];
  readonly statutOptions: SelectOption[] = [
    { value: '', label: 'Tous les statuts' },
    ...this.jobStatuses.map(s => ({ value: s, label: JOB_STATUS_LABELS[s] })),
  ];

  /** Formulaire d'offre : mêmes listes que les anciens <select>, en champs (pas en getters). */
  readonly workModeOptions: SelectOption[] = [
    { value: '', label: '-- Sélectionner --' },
    ...this.workModes.map(m => ({ value: m, label: WORK_MODE_LABELS[m] })),
  ];
  readonly educationLevelOptions: SelectOption[] = [
    { value: '',            label: '-- Sélectionner --' },
    { value: 'HIGH_SCHOOL', label: 'Baccalauréat' },
    { value: 'BACHELOR',    label: 'Licence' },
    { value: 'INGENIEUR',   label: 'Ingénieur' },
    { value: 'MASTER',      label: 'Master' },
    { value: 'PhD',         label: 'Doctorat' },
  ];
  readonly jobStatusOptions: SelectOption[] =
    this.jobStatuses.map(s => ({ value: s, label: JOB_STATUS_LABELS[s] }));

  surTri(valeur: string): void { this.sortBy = valeur; this.applyFilters(); }
  surStatut(valeur: string): void { this.statusFilter = valeur; this.applyFilters(); }
  readonly workModeLabels = WORK_MODE_LABELS;
  readonly contractTypeLabels = CONTRACT_TYPE_LABELS;
  readonly jobStatusLabels = JOB_STATUS_LABELS;
  skillsInput = '';
  skillSearchTerm = '';
  skillSuggestions: string[] = [];
  showSkillSuggestions = false;
  applicantsModal = false;
  applicantsLoading = false;
  applicantsError = '';
  selectedJobId: string | null = null;
  selectedJobTitle = '';
  applicants: Application[] = [];
  paginatedApplicants: Application[] = [];
  applicantCurrentPage = 1;
  applicantPageSize = 10;
  applicantTotalPages = 1;
  applicantSearch = '';
  applicantStatusFilter = '';
  /** Tous les statuts du backend, pour le filtre (avant : 4 seulement). */
  readonly applicationStatuses = APPLICATION_STATUSES;
  readonly appStatusLabel = applicationStatusLabel;
  readonly isTerminalStatus = isTerminalStatus;
  private readonly statusOptionsCache = new Map<string, SelectOption[]>();

  /** Statut actuel + transitions admises : le sélecteur n'est jamais vide. */
  statusOptions(status: string): SelectOption[] {
    let options = this.statusOptionsCache.get(status);
    if (!options) {
      options = statusOptionsFor(status).map(s => ({ value: s, label: applicationStatusLabel(s) }));
      this.statusOptionsCache.set(status, options);
    }
    return options;
  }
  applicantTab: 'list' | 'ranking' | 'analysis' = 'list';
  analysisFocusTab: 'score' | 'cv' = 'score';
  selectedApplicationId: string | null = null;
  cvPreviewOpen = false;
  cvPreviewPath = '';
  candidateCounts: Map<string, number> = new Map();

  // Workflow modals
  showInterviewModal = false;
  showNegotiationModal = false;
  workflowApplicationId: string | null = null;
  negotiationOffer: number | null = null;
  workflowLoading = false;
  workflowMessage = '';
  /** Increment to force the candidate-ranking component to refetch its data
   *  (so newly-scheduled interviews immediately disable the Planifier button). */
  rankingRefreshTrigger = 0;

  // Suggestion salariale (création/édition d'offre — poste seul, pas de candidat)
  salarySuggestion: SalarySuggestion | null = null;
  suggestingSalary = false;

  /**
   * Remplissage assisté depuis un texte libre.
   *
   * Même principe que la suggestion de salaire juste au-dessus : l'agent
   * PROPOSE des champs, ils ne s'appliquent qu'au clic sur « Utiliser ces
   * informations » — jamais automatiquement à la réponse du serveur.
   */
  /** Replié par défaut : c'est un raccourci facultatif, pas la première
   *  chose que l'œil doit rencontrer en ouvrant le formulaire. */
  jobPromptOpen = false;
  jobPromptText = '';
  extractingJob = false;
  jobExtraction: JobExtractionResponse | null = null;
  /** Champs déjà présents avant l'extraction : on ne les écrase pas d'office. */
  jobExtractionOverwrite = false;

  toggleJobPrompt(): void {
    this.jobPromptOpen = !this.jobPromptOpen;
  }

  // Négociation — profil du candidat sélectionné + autres candidats de l'offre
  negotiationCandidateName = '';
  otherCandidatesForJob: Array<{ candidate_name: string; match_score: number; status: string }> = [];

  // Négociation — chat avec l'assistant IA
  negotiationChatMessages: NegotiationChatMessage[] = [];
  negotiationChatInput = '';
  negotiationChatSending = false;

  constructor(
    private recruitment: RecruitmentService,
    private router: Router,
  ) {}

  ngOnInit() {
    this.loadJobs();
  }

  loadJobs() {
    this.jobsLoading = true;
    // `getJobsForManagement` (et non `getJobs`) : le backoffice doit voir les
    // brouillons et les offres fermées, que le listing public masque.
    this.recruitment.getJobsForManagement(1, 100, this.searchTerm, this.sortBy, {
      status: this.statusFilter || undefined,
    }).subscribe({
      next: res => {
        this.jobs = res.items;
        this.filteredJobs = res.items;
        this.jobsLoading = false;
        this.loadCandidateCounts();
      },
      error: () => { this.jobsLoading = false; }
    });
  }

  loadCandidateCounts() {
    this.jobs.forEach(job => {
      this.recruitment.getApplicationsByJob(job.id).subscribe({
        next: apps => this.candidateCounts.set(job.id, apps.length)
      });
    });
  }

  getCandidateCount(jobId: string): number {
    return this.candidateCounts.get(jobId) || 0;
  }

  // ── Conditions du poste (affichage tableau) ──────────────────────
  workModeLabel(job: JobOffer): string {
    return job.work_mode ? WORK_MODE_LABELS[job.work_mode] : '';
  }

  contractTypeLabel(job: JobOffer): string {
    return contractTypesLabel(job.contract_types);
  }

  /** Ouverture du menu déroulant des types de contrat. */
  contractTypesOpen = false;

  /**
   * Ce que le déclencheur affiche une fois le menu refermé.
   *
   * Au-delà de trois types, l'énumération dépasserait la largeur du champ et
   * serait tronquée : on bascule alors sur un décompte, qui reste exact.
   */
  get contractTypesSummary(): string {
    const choisis = this.formData.contract_types;
    if (!choisis.length) return '-- Sélectionner --';
    if (choisis.length > 3) return `${choisis.length} types sélectionnés`;
    return contractTypesLabel(choisis);
  }

  toggleContractTypesMenu(): void {
    this.contractTypesOpen = !this.contractTypesOpen;
  }

  closeContractTypesMenu(): void {
    this.contractTypesOpen = false;
  }

  clearContractTypes(): void {
    this.formData.contract_types = [];
  }

  /**
   * Referme le menu sur un clic à l'extérieur.
   *
   * Le conteneur `.ms` arrête la propagation, ce gestionnaire ne reçoit donc
   * que les clics qui lui sont réellement extérieurs.
   */
  @HostListener('document:click')
  onDocumentClick(): void {
    this.contractTypesOpen = false;
  }

  /** Échap referme le menu sans quitter le formulaire. */
  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.contractTypesOpen = false;
  }

  /** Une case cochée = ce type de contrat est accepté par l'offre. */
  isContractTypeSelected(type: ContractType): boolean {
    return this.formData.contract_types.includes(type);
  }

  /**
   * Ajoute ou retire un type de contrat.
   *
   * On reconstruit le tableau plutôt que de le muter : `formData` est lu par
   * le template, et une mutation en place ne déclenche pas toujours la
   * détection de changement sur les liaisons qui en dépendent.
   */
  toggleContractType(type: ContractType): void {
    this.formData.contract_types = this.isContractTypeSelected(type)
      ? this.formData.contract_types.filter(t => t !== type)
      : [...this.formData.contract_types, type];
  }

  statusLabel(job: JobOffer): string {
    return JOB_STATUS_LABELS[job.status || 'PUBLISHED'];
  }

  /** Une offre expirée reste visible en backoffice mais n'accepte plus de candidature. */
  isExpired(job: JobOffer): boolean {
    return !!job.expires_at && new Date(job.expires_at).getTime() < Date.now();
  }

  applyFilters() {
    this.loadJobs();
  }

  openCreateDrawer() {
    if (!this.peutModifierOffres) return;
    this.editingJob = null;
    this.formData = JobsManagementComponent.emptyForm();
    this.skillsInput = '';
    this.resetSkillSearch();
    this.jobPromptOpen = false;
    this.jobPromptText = '';
    this.jobExtraction = null;
    this.drawerOpen = true;
  }

  editJob(job: JobOffer) {
    if (!this.peutModifierOffres) return;
    this.editingJob = job;
    this.formData = {
      ...JobsManagementComponent.emptyForm(),
      title: job.title,
      description: job.description,
      salary_min: job.salary_min,
      salary_max: job.salary_max,
      required_skills: job.required_skills || [],
      required_experience_years: job.required_experience_years ?? null,
      required_education_level: job.required_education_level || '',
      weight_skills: job.weight_skills || 0.5,
      weight_experience: job.weight_experience || 0.3,
      weight_education: job.weight_education || 0.2,
      work_mode: job.work_mode || '',
      contract_types: [...(job.contract_types ?? [])],
      status: job.status || 'PUBLISHED',
      expires_at: this.toDatetimeLocal(job.expires_at),
    };
    this.skillsInput = (job.required_skills || []).join(', ');
    this.resetSkillSearch();
    this.drawerOpen = true;
  }

  /** ISO serveur → valeur acceptée par `<input type="datetime-local">` (heure locale, sans zone). */
  private toDatetimeLocal(iso?: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  // ── Auto-complétion des compétences ──────────────────────────────
  private resetSkillSearch() {
    this.skillSearchTerm = '';
    this.skillSuggestions = [];
    this.showSkillSuggestions = false;
  }

  private currentSkillsLower(): string[] {
    return this.skillsInput.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  }

  onSkillSearchInput() {
    const term = this.skillSearchTerm.trim().toLowerCase();
    if (!term) {
      this.skillSuggestions = [];
      this.showSkillSuggestions = false;
      return;
    }
    const already = this.currentSkillsLower();
    this.skillSuggestions = TECH_SKILLS
      .filter(s => s.toLowerCase().includes(term) && !already.includes(s.toLowerCase()))
      .slice(0, 8);
    this.showSkillSuggestions = true;
  }

  addSkill(skill: string) {
    const trimmed = skill.trim();
    if (!trimmed || this.currentSkillsLower().includes(trimmed.toLowerCase())) {
      this.resetSkillSearch();
      return;
    }
    this.skillsInput = this.skillsInput.trim() ? `${this.skillsInput.trim()}, ${trimmed}` : trimmed;
    this.resetSkillSearch();
  }

  /** Compétences saisies, une par pastille (stockées en texte séparé par des virgules). */
  get skillsList(): string[] {
    return this.skillsInput.split(',').map(s => s.trim()).filter(Boolean);
  }

  removeSkill(skill: string) {
    this.skillsInput = this.skillsList.filter(s => s !== skill).join(', ');
  }

  onSkillSearchKeydown(event: KeyboardEvent) {
    // Retour arrière dans une recherche vide : retire la dernière pastille.
    if (event.key === 'Backspace' && !this.skillSearchTerm && this.skillsList.length) {
      this.removeSkill(this.skillsList[this.skillsList.length - 1]);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (this.skillSuggestions.length) {
        this.addSkill(this.skillSuggestions[0]);
      } else if (this.skillSearchTerm.trim()) {
        this.addSkill(this.skillSearchTerm);
      }
    } else if (event.key === 'Escape') {
      this.showSkillSuggestions = false;
    }
  }

  /** Délai avant de masquer la liste, pour laisser le clic sur une suggestion s'exécuter avant le blur. */
  hideSkillSuggestionsDelayed() {
    setTimeout(() => { this.showSkillSuggestions = false; }, 150);
  }

  saveJob() {
    if (this.savingJob) return;
    if (!this.formData.title || !this.formData.description) return;

    // Parse skills from the textarea input
    const skills = this.skillsInput
      .split(',')
      .map(s => s.trim())
      .filter(s => s.length > 0);

    // Les `<select>`/`<input>` vides valent '' : le backend attend null, sinon
    // la chaîne vide échoue sur les motifs de validation (work_mode,
    // contract_type) et sur le parsing de la date.
    const jobData = {
      ...this.formData,
      required_skills: skills,
      work_mode: this.formData.work_mode || null,
      contract_types: this.formData.contract_types.length ? this.formData.contract_types : null,
      expires_at: this.formData.expires_at
        ? new Date(this.formData.expires_at).toISOString()
        : null,
    };

    this.savingJob = true;

    if (this.editingJob) {
      this.recruitment.updateJob(this.editingJob.id, jobData).subscribe({
        next: () => {
          this.savingJob = false;
          this.closeDrawer();
          this.loadJobs();
        },
        error: err => {
          this.savingJob = false;
          this.toast.fromHttpError(err, "La modification de l'offre a échoué.");
        }
      });
    } else {
      this.recruitment.createJob(jobData).subscribe({
        next: () => {
          this.savingJob = false;
          this.closeDrawer();
          this.loadJobs();
        },
        error: err => {
          this.savingJob = false;
          this.toast.fromHttpError(err, "La création de l'offre a échoué.");
        }
      });
    }
  }

  closeDrawer() {
    this.drawerOpen = false;
    this.contractTypesOpen = false;
    this.editingJob = null;
    this.formData = JobsManagementComponent.emptyForm();
    this.skillsInput = '';
    this.resetSkillSearch();
    this.jobPromptOpen = false;
    this.jobPromptText = '';
    this.jobExtraction = null;
  }

  toggleJob(jobId: string, isActive: boolean) {
    if (!this.peutModifierOffres) return;
    this.recruitment.updateJob(jobId, { is_active: isActive }).subscribe({
      next: () => this.loadJobs()
    });
  }

  async deleteJob(job: JobOffer) {
    if (!this.peutSupprimerOffres) return;
    const ok = await this.confirmService.askDelete(
      `Supprimer définitivement l'offre « ${job.title} » ? Cette action est irréversible.`,
      "Supprimer l'offre",
    );
    if (!ok) return;

    this.recruitment.deleteJob(job.id).subscribe({
      next: () => {
        this.toast.success('Offre supprimée.');
        this.loadJobs();
      },
      error: err => this.toast.fromHttpError(err, "La suppression de l'offre a échoué.")
    });
  }

  viewApplicants(jobId: string) {
    this.selectedJobId = jobId;
    const job = this.jobs.find(j => j.id === jobId);
    this.selectedJobTitle = job?.title || '';
    this.applicants = [];
    this.paginatedApplicants = [];
    this.applicantTab = 'list';
    this.applicantSearch = '';
    this.applicantStatusFilter = '';
    this.applicantsError = '';
    this.applicantsLoading = true;
    this.applicantsModal = true;

    this.loadApplicants(jobId);
  }

  reloadApplicants() {
    if (this.selectedJobId) {
      this.applicantsError = '';
      this.applicantsLoading = true;
      this.loadApplicants(this.selectedJobId);
    }
  }

  private loadApplicants(jobId: string) {
    this.recruitment.getApplicationsByJob(jobId).subscribe({
      next: apps => {
        this.applicants = apps;
        this.applicantCurrentPage = 1;
        this.updateApplicantPagination();
        this.applicantsLoading = false;
      },
      error: error => {
        this.applicants = [];
        this.paginatedApplicants = [];
        this.applicantsLoading = false;
        if (error.status === 401) {
          this.applicantsError = 'Votre session a expiré. Reconnectez-vous puis réessayez.';
        } else if (error.status === 403) {
          this.applicantsError = 'Vous n’avez pas les permissions nécessaires pour consulter ces candidatures.';
        } else {
          this.applicantsError = error.error?.detail || 'Une erreur est survenue pendant le chargement.';
        }
      }
    });
  }

  updateApplicantPagination() {
    const filtered = this.filteredApplicants;
    this.applicantTotalPages = Math.max(1, Math.ceil(filtered.length / this.applicantPageSize));
    const start = (this.applicantCurrentPage - 1) * this.applicantPageSize;
    const end = start + this.applicantPageSize;
    this.paginatedApplicants = filtered.slice(start, end);
  }

  get filteredApplicants(): Application[] {
    const search = this.applicantSearch.trim().toLowerCase();
    return this.applicants.filter(app => {
      const matchesSearch = !search || (app.candidate_name || '').toLowerCase().includes(search);
      const matchesStatus = !this.applicantStatusFilter || app.status === this.applicantStatusFilter;
      return matchesSearch && matchesStatus;
    });
  }

  filterApplicants(): void {
    this.applicantCurrentPage = 1;
    this.updateApplicantPagination();
  }

  exportApplicants(): void {
    const rows = this.filteredApplicants;
    const header = ['Candidat', 'CV', 'Statut', 'Date'];
    const csv = [
      header,
      ...rows.map(app => [
        app.candidate_name || app.candidate_id,
        app.cv_file_path,
        app.status,
        app.created_at,
      ]),
    ].map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'candidatures.csv';
    link.click();
    URL.revokeObjectURL(url);
  }

  goToApplicantPage(page: number) {
    this.applicantCurrentPage = page;
    this.updateApplicantPagination();
  }

  onApplicantPageSizeChange(newSize: number) {
    this.applicantPageSize = newSize;
    this.applicantCurrentPage = 1;
    this.updateApplicantPagination();
  }

  closeApplicants() {
    this.applicantsModal = false;
    this.applicantsLoading = false;
    this.applicantsError = '';
    this.applicants = [];
    this.paginatedApplicants = [];
  }

  previewCV(cvPath: string) {
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
    this.cvPreviewOpen = false;
    if (this.cvPreviewPath.startsWith('blob:')) {
      URL.revokeObjectURL(this.cvPreviewPath);
    }
    this.cvPreviewPath = '';
  }

  viewAnalysis(applicationId: string) {
    this.selectedApplicationId = applicationId;
    this.applicantTab = 'analysis';
    this.analysisFocusTab = 'score';
  }


  downloadCV(cvPath: string) {
    this.recruitment.downloadCVAsBlob(cvPath).subscribe({
      next: blob => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = cvPath.split('/').pop() || 'cv.pdf';
        link.click();
        URL.revokeObjectURL(url);
      },
      error: err => this.toast.fromHttpError(err, 'Le téléchargement du CV a échoué.')
    });
  }

  updateAppStatus(app: Application, status: string) {
    if (status === app.status) return;
    this.recruitment.updateApplication(app.id, status).subscribe({
      // Transition refusée : on recharge pour que le sélecteur revienne au statut réel.
      error: err => {
        this.toast.fromHttpError(err, 'Changement de statut refusé.');
        if (this.selectedJobId) this.loadApplicants(this.selectedJobId);
      },
      next: () => {
        if (this.selectedJobId) {
          this.recruitment.getApplicationsByJob(this.selectedJobId).subscribe({
            next: apps => {
              this.applicants = apps;
              this.updateApplicantPagination();
            }
          });
        }
      }
    });
  }

  // ── Workflow handlers ──────────────────────────────────────────

  onScheduleInterview(action: WorkflowAction) {
    this.workflowApplicationId = action.applicationId;
    this.showInterviewModal = true;
  }

  /**
   * Envoi d'un test : on renvoie vers l'écran de préparation, offre et
   * candidature déjà choisies. Reconstruire ici la sélection des questions
   * dupliquerait un écran qui existe — et les compteurs de couverture avec.
   */
  onSendTest(action: WorkflowAction) {
    this.router.navigate(['/admin/assessment'], {
      queryParams: { job: this.selectedJobId, application: action.applicationId },
    });
  }

  onInterviewSchedulerClosed(success: boolean) {
    this.showInterviewModal = false;
    this.workflowApplicationId = null;
    if (success) {
      this.workflowMessage = 'Entretien planifié avec succès. Email envoyé au candidat.';
      // Force the candidate-ranking to refresh so the Planifier button
      // immediately disables for this candidate.
      this.rankingRefreshTrigger++;
    }
  }

  /**
   * Ouvre la modale de négociation salariale.
   *
   * ⚠ SANS POINT D'ENTRÉE ACTUELLEMENT. Le classement des candidats ne propose
   * plus « Lancer Négociation » : négocier suppose une évaluation préalable —
   * test technique rendu ou entretien passé — qui n'a pas eu lieu à ce stade.
   *
   * Cette méthode et la modale qu'elle ouvre sont CONSERVÉES intactes : elles
   * portent tout le flux (offre initiale, échange assisté, comparaison aux
   * autres candidats) et devront être rebranchées depuis l'écran où
   * l'évaluation a effectivement eu lieu. Les supprimer obligerait à les
   * réécrire.
   */
  onStartNegotiation(action: WorkflowAction) {
    this.workflowApplicationId = action.applicationId;
    this.negotiationOffer = null;
    this.negotiationChatMessages = [];
    this.negotiationChatInput = '';
    this.otherCandidatesForJob = [];

    const app = this.applicants.find(a => a.id === action.applicationId);
    this.negotiationCandidateName = app?.candidate_name || '';

    this.showNegotiationModal = true;

    if (this.selectedJobId) {
      this.recruitment.getRankedCandidates(this.selectedJobId).subscribe({
        next: res => {
          this.otherCandidatesForJob = (res.ranking || [])
            .filter(c => c.application_id !== action.applicationId)
            .slice(0, 5)
            .map(c => ({
              candidate_name: c.candidate_name || `#${c.candidate_id.slice(0, 8)}`,
              match_score: c.total_score,
              status: '',
            }));
        },
        error: () => { /* non-bloquant : le chat fonctionne sans cette liste */ }
      });
    }
  }

  closeNegotiationModal() {
    this.showNegotiationModal = false;
    this.workflowApplicationId = null;
    this.negotiationChatMessages = [];
    this.negotiationChatInput = '';
    this.otherCandidatesForJob = [];
    this.negotiationCandidateName = '';
  }

  confirmNegotiation() {
    if (!this.workflowApplicationId || !this.negotiationOffer) return;
    this.workflowLoading = true;
    this.recruitment.startNegotiation(this.workflowApplicationId, this.negotiationOffer).subscribe({
      next: (res: any) => {
        this.workflowLoading = false;
        if (res?.negotiation_status) {
          const statusFr: Record<string, string> = {
            ACCEPTED: 'Accord trouvé ✅', REJECTED: 'Offre rejetée ❌', COMPROMIS: 'Compromis 🤝',
          };
          this.workflowMessage =
            `${statusFr[res.negotiation_status] || res.negotiation_status} — ` +
            `salaire prédit ${res.predicted_salary} TND, offre finale ${res.final_salary} TND ` +
            `(${res.rounds || 0} tour(s)). ${res.reason || ''}`;
        } else {
          this.workflowMessage = res?.message || 'Négociation lancée.';
        }
        // La modale reste ouverte : le RH peut continuer à discuter avec
        // l'assistant (autre montant, comparaison avec d'autres candidats...).
      },
      error: () => {
        this.workflowLoading = false;
        this.workflowMessage = 'Erreur lors du lancement de la négociation.';
      }
    });
  }

  sendNegotiationChat() {
    const message = this.negotiationChatInput.trim();
    if (!message || !this.workflowApplicationId || this.negotiationChatSending) return;

    this.negotiationChatMessages.push({ role: 'user', content: message });
    this.negotiationChatInput = '';
    this.negotiationChatSending = true;

    const history = this.negotiationChatMessages.slice(0, -1);
    this.recruitment.negotiationChat(this.workflowApplicationId, message, history).subscribe({
      next: res => {
        this.negotiationChatSending = false;
        this.negotiationChatMessages.push({ role: 'assistant', content: res.reply });
      },
      error: err => {
        this.negotiationChatSending = false;
        this.negotiationChatMessages.push({
          role: 'assistant',
          content: "Désolé, je n'ai pas pu répondre (" + (err?.error?.detail || 'erreur serveur') + ').',
        });
      }
    });
  }

  suggestSalary() {
    if (!this.formData.title || this.suggestingSalary) return;
    this.suggestingSalary = true;
    this.salarySuggestion = null;
    this.recruitment.predictSalary({
      title: this.formData.title,
      description: this.formData.description,
      skills_text: this.skillsInput,
      experience_years: this.formData.required_experience_years,
    }).subscribe({
      next: res => {
        this.suggestingSalary = false;
        this.salarySuggestion = res;
      },
      error: err => {
        this.suggestingSalary = false;
        this.toast.fromHttpError(err, 'Impossible de calculer une suggestion de salaire.');
      }
    });
  }

  applySalarySuggestion() {
    if (!this.salarySuggestion) return;
    this.formData.salary_min = this.salarySuggestion.range_min;
    this.formData.salary_max = this.salarySuggestion.range_max;
  }

  /**
   * Demande à l'agent d'extraire les champs du texte libre.
   *
   * N'écrase JAMAIS un champ déjà rempli sans confirmation explicite : un RH
   * qui a commencé à saisir le formulaire, puis colle un texte pour compléter
   * le reste, ne doit pas voir son travail remplacé en silence.
   */
  extractJobFromPrompt(): void {
    const texte = this.jobPromptText.trim();
    if (!texte || this.extractingJob) return;
    this.extractingJob = true;
    this.jobExtraction = null;
    this.recruitment.extractJobFromText(texte).subscribe({
      next: (res) => {
        this.extractingJob = false;
        this.jobExtraction = res;
        if (!res.ok) {
          this.toast.info(res.reason || "L'extraction n'a rien donné.");
        }
      },
      error: (err) => {
        this.extractingJob = false;
        this.toast.fromHttpError(err, "L'extraction a échoué.");
      },
    });
  }

  /**
   * Applique les champs proposés au formulaire.
   *
   * Par défaut, seuls les champs ENCORE VIDES sont remplis — un titre déjà
   * saisi à la main n'est pas remplacé. `jobExtractionOverwrite` lève ce
   * garde-fou pour qui veut explicitement tout reprendre de la proposition.
   */
  applyJobExtraction(): void {
    const champs = this.jobExtraction?.fields;
    if (!champs) return;
    const remplacer = this.jobExtractionOverwrite;

    if (champs.title && (remplacer || !this.formData.title)) {
      this.formData.title = champs.title;
    }
    if (champs.description && (remplacer || !this.formData.description)) {
      this.formData.description = champs.description;
    }
    if (champs.required_skills?.length && (remplacer || !this.formData.required_skills.length)) {
      this.formData.required_skills = champs.required_skills;
      this.skillsInput = champs.required_skills.join(', ');
    }
    if (champs.required_experience_years != null
        && (remplacer || this.formData.required_experience_years == null)) {
      this.formData.required_experience_years = champs.required_experience_years;
    }
    if (champs.required_education_level && (remplacer || !this.formData.required_education_level)) {
      this.formData.required_education_level = champs.required_education_level;
    }
    if (champs.work_mode && (remplacer || !this.formData.work_mode)) {
      this.formData.work_mode = champs.work_mode as WorkMode;
    }
    if (champs.contract_types?.length && (remplacer || !this.formData.contract_types.length)) {
      this.formData.contract_types = champs.contract_types as ContractType[];
    }

    this.jobExtraction = null;
    this.jobPromptText = '';
    this.jobPromptOpen = false;
    this.toast.success('Champs pré-remplis — relisez-les avant de publier.');
  }

  effacerJobExtraction(): void {
    this.jobExtraction = null;
  }

  /** Libellé du mode de travail proposé, ou la valeur brute si inconnue. */
  jobExtractionWorkModeLabel(mode: string): string {
    return (this.workModeLabels as Record<string, string>)[mode] || mode;
  }


  async onRejectCandidate(action: WorkflowAction) {
    const ok = await this.confirmService.ask({
      title: 'Rejeter la candidature',
      message: `Rejeter cette candidature (score ${action.score.toFixed(0)}/100) ? Un email de refus sera envoyé au candidat.`,
      confirmLabel: 'Rejeter',
      danger: true,
    });
    if (!ok) return;
    this.recruitment.rejectApplication(action.applicationId).subscribe({
      next: () => {
        this.workflowMessage = 'Candidature rejetée. Email envoyé au candidat.';
      },
      error: () => {
        this.workflowMessage = 'Erreur lors du rejet de la candidature.';
      }
    });
  }

  closeWorkflowMessage() {
    this.workflowMessage = '';
  }
}
