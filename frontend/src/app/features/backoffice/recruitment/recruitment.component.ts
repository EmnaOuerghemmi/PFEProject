import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import {
  RecruitmentService, JobOffer, RecruitmentSummary, educationLevelLabel,
} from '../../../core/services/recruitment.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import {
  SemanticService, SemanticStatus, SemanticMatch,
} from '../../../core/services/semantic.service';
import {
  CandidateRankingComponent, WorkflowAction,
} from '../../../shared/components/candidate-ranking/candidate-ranking.component';
import {
  InterviewSchedulerComponent,
} from '../../../shared/components/interview-scheduler/interview-scheduler.component';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';

/**
 * Un candidat, et toutes ses candidatures retrouvées par la recherche.
 *
 * La recherche travaille par CANDIDATURE — une même personne qui a postulé à
 * trois offres remontait donc trois fois de suite, ce qui donnait une liste où
 * le même nom se répétait sans qu'on sache s'il s'agissait d'un doublon. On
 * regroupe par personne : une carte par candidat, ses candidatures listées
 * dedans.
 */
export interface CandidateGroup {
  candidateId: string;
  /** Compte utilisateur, pour ouvrir sa fiche. Absent si le candidat n'en a pas. */
  userId: string | null;
  candidateName: string;
  /** Meilleure correspondance parmi ses candidatures : le signal du candidat. */
  bestScore: number;
  experienceYears: number | null;
  skills: string[];
  applications: SemanticMatch[];
  /** Candidature sur laquelle portera l'invitation à un entretien. */
  selectedApplicationId: string;
  /** Options du sélecteur de candidature — calculées une fois (un champ, pas un getter). */
  applicationOptions: SelectOption[];
}

@Component({
  selector: 'app-recruitment',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink,
    CandidateRankingComponent, InterviewSchedulerComponent, SelectComponent,
  ],
  templateUrl: './recruitment.component.html',
  styleUrls: ['./recruitment.component.css'],
})
export class RecruitmentComponent implements OnInit {
  private confirmService = inject(ConfirmService);

  summary: RecruitmentSummary | null = null;
  jobs: JobOffer[] = [];
  selectedJobId = '';
  analyzing = false;
  message = '';
  messageTone: 'info' | 'success' | 'error' = 'info';
  rankingRefresh = 0;
  candidateCounts = new Map<string, number>();
  jobSearch = '';

  // ── Recherche par similarité ──
  semanticStatus: SemanticStatus | null = null;
  semanticGroups: CandidateGroup[] = [];
  semanticLoading = false;
  semanticRan = false;

  // ── Modale « Contacter » (invitation à un entretien) ──
  showContactModal = false;
  contactApplicationId = '';
  contactCandidateName = '';
  contactMessage = '';

  constructor(
    private recruitment: RecruitmentService,
    private semantic: SemanticService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.loadSummary();
    this.loadJobs();
    this.semantic.getStatus().subscribe({
      next: s => this.semanticStatus = s,
      error: () => {},
    });
  }

  // ════════════ Matching sémantique ════════════

  runSemanticMatch(): void {
    if (!this.selectedJobId) return;
    this.semanticLoading = true;
    this.semanticRan = true;
    this.semanticGroups = [];
    this.semantic.matchCandidates(this.selectedJobId, 20).subscribe({
      next: res => {
        this.semanticGroups = this.grouper(res.results);
        this.semanticLoading = false;
      },
      error: err => {
        this.semanticLoading = false;
        this.messageTone = 'error';
        this.message = err?.error?.detail || 'Recherche par similarité indisponible.';
      },
    });
  }

  /**
   * Une carte par personne, ses candidatures dedans.
   *
   * L'ordre de la liste est celui du serveur (correspondance décroissante) :
   * le premier résultat d'un candidat donne donc sa meilleure correspondance,
   * et l'ordre des candidats suit celui de leur meilleur score.
   */
  private grouper(matches: SemanticMatch[]): CandidateGroup[] {
    const parCandidat = new Map<string, CandidateGroup>();

    for (const m of matches) {
      const existant = parCandidat.get(m.candidate_id);
      if (existant) {
        existant.applications.push(m);
        // Les compétences extraites peuvent différer d'un CV à l'autre : on
        // réunit ce qu'on sait de la personne plutôt que de n'en montrer
        // qu'une version.
        for (const s of m.skills) {
          if (!existant.skills.includes(s)) existant.skills.push(s);
        }
        if (existant.experienceYears === null) existant.experienceYears = m.experience_years;
        continue;
      }
      parCandidat.set(m.candidate_id, {
        candidateId: m.candidate_id,
        userId: m.user_id,
        candidateName: m.candidate_name,
        bestScore: m.semantic_score,
        experienceYears: m.experience_years,
        skills: [...m.skills],
        applications: [m],
        selectedApplicationId: m.application_id,
        applicationOptions: [],
      });
    }
    const groupes = [...parCandidat.values()];
    for (const g of groupes) {
      g.applicationOptions = g.applications.map(a => ({
        value: a.application_id,
        label: `${a.job_title} — ${Math.round(a.semantic_score)} %`,
      }));
    }
    return groupes;
  }

  /** Niveau de correspondance — le chiffre brut seul ne se lit pas. */
  niveau(score: number): 'forte' | 'moyenne' | 'faible' {
    if (score >= 50) return 'forte';
    if (score >= 35) return 'moyenne';
    return 'faible';
  }

  niveauLabel(score: number): string {
    return {
      forte: 'Forte correspondance',
      moyenne: 'Correspondance moyenne',
      faible: 'Correspondance faible',
    }[this.niveau(score)];
  }

  candidatureDe(group: CandidateGroup): SemanticMatch {
    return group.applications.find(a => a.application_id === group.selectedApplicationId)
      ?? group.applications[0];
  }

  // ── Contacter : invitation à un entretien ──

  ouvrirContact(group: CandidateGroup): void {
    const candidature = this.candidatureDe(group);
    this.contactApplicationId = candidature.application_id;
    this.contactCandidateName = group.candidateName;
    this.contactMessage = this.messageParDefaut(group.candidateName);
    this.showContactModal = true;
  }

  fermerContact(envoye: boolean): void {
    this.showContactModal = false;
    this.contactApplicationId = '';
    if (envoye) {
      this.messageTone = 'success';
      this.message = `Invitation envoyée à ${this.contactCandidateName}. `
        + 'Le candidat choisira son créneau ; un test technique lui sera envoyé dès sa confirmation.';
      // Le classement au-dessus affiche l'état d'entretien : il vient de changer.
      this.rankingRefresh++;
    }
  }

  /**
   * Message prérempli, modifiable avant envoi.
   *
   * Il nomme l'offre SÉLECTIONNÉE, pas celle de la candidature : c'est le
   * poste pour lequel le RH recrute et pour lequel la recherche a fait
   * remonter cette personne — elle, a pu postuler à une autre offre.
   */
  private messageParDefaut(nom: string): string {
    const poste = this.selectedJob?.title || 'le poste ouvert';
    return `Bonjour ${nom},\n\n`
      + `Votre profil a retenu notre attention pour le poste « ${poste} ».\n\n`
      + `Si ce poste vous intéresse, nous aimerions échanger avec vous lors d'un entretien : `
      + `choisissez simplement le créneau qui vous convient parmi ceux proposés.\n\n`
      + `À bientôt,\nL'équipe recrutement`;
  }

  semanticBackendLabel(): string {
    if (!this.semanticStatus) return '';
    return this.semanticStatus.effective_backend === 'hash-v1'
      ? 'recherche par mots-clés' : 'recherche par sens active';
  }

  trackGroup(_i: number, g: CandidateGroup): string { return g.candidateId; }

  loadSummary(): void {
    this.recruitment.getRecruitmentSummary().subscribe({
      next: s => this.summary = s,
      error: () => {},
    });
  }

  loadJobs(): void {
    this.recruitment.getJobs(1, 100).subscribe({
      next: res => {
        this.jobs = res.items;
        if (!this.selectedJobId && this.jobs.length) {
          this.selectedJobId = this.jobs[0].id;
        }
        this.jobs.forEach(j => {
          this.recruitment.getApplicationsByJob(j.id).subscribe({
            next: apps => this.candidateCounts.set(j.id, apps.length),
            error: () => {},
          });
        });
      },
    });
  }

  get filteredJobs(): JobOffer[] {
    const q = this.jobSearch.trim().toLowerCase();
    if (!q) return this.jobs;
    return this.jobs.filter(j => j.title.toLowerCase().includes(q));
  }

  get selectedJob(): JobOffer | undefined {
    return this.jobs.find(j => j.id === this.selectedJobId);
  }

  count(jobId: string): number {
    return this.candidateCounts.get(jobId) || 0;
  }

  selectJob(id: string): void {
    this.selectedJobId = id;
    this.message = '';
    this.semanticGroups = [];
    this.semanticRan = false;
  }

  eduLabel(level: string | null | undefined): string {
    return educationLevelLabel(level) || '—';
  }

  analyzeAll(): void {
    if (!this.selectedJobId) return;
    this.analyzing = true;
    this.message = '';
    this.recruitment.analyzeAllForJob(this.selectedJobId).subscribe({
      next: () => {
        this.analyzing = false;
        this.messageTone = 'info';
        this.message = 'Analyse IA lancée. Le classement se met à jour dans quelques instants…';
        setTimeout(() => this.rankingRefresh++, 2500);
      },
      error: err => {
        this.analyzing = false;
        this.messageTone = 'error';
        this.message = err.error?.detail || 'Erreur lors du lancement de l’analyse.';
      },
    });
  }

  async onReject(a: WorkflowAction): Promise<void> {
    const ok = await this.confirmService.ask({
      title: 'Rejeter le candidat',
      message: `Rejeter ce candidat (score ${a.score.toFixed(0)}/100) ? Un email de refus lui sera envoyé.`,
      confirmLabel: 'Rejeter',
      danger: true,
    });
    if (!ok) return;
    this.recruitment.rejectApplication(a.applicationId).subscribe({
      next: () => { this.messageTone = 'success'; this.message = 'Candidature rejetée. Email envoyé.'; this.rankingRefresh++; },
      error: () => { this.messageTone = 'error'; this.message = 'Erreur lors du rejet.'; },
    });
  }

  /**
   * ⚠ SANS POINT D'ENTRÉE ACTUELLEMENT — voir la note équivalente dans
   * `jobs-management.component.ts`. Le classement ne propose plus de lancer
   * une négociation avant évaluation.
   */
  onStartNegotiation(a: WorkflowAction): void {
    const offer = Number(window.prompt('Offre salariale initiale (k TND) :', '50'));
    if (!offer || offer <= 0) return;
    this.recruitment.startNegotiation(a.applicationId, offer).subscribe({
      next: (res: any) => {
        this.messageTone = 'success';
        if (res?.negotiation_status) {
          const statusFr: Record<string, string> = {
            ACCEPTED: 'Accord trouvé ✅', REJECTED: 'Offre rejetée ❌', COMPROMIS: 'Compromis 🤝',
          };
          this.message =
            `${statusFr[res.negotiation_status] || res.negotiation_status} — ` +
            `salaire prédit ${res.predicted_salary} TND, offre finale ${res.final_salary} TND ` +
            `(${res.rounds || 0} tour(s)).`;
        } else {
          this.message = res?.message || 'Négociation lancée.';
        }
      },
      error: () => { this.messageTone = 'error'; this.message = 'Erreur lors du lancement de la négociation.'; },
    });
  }

  onScheduleInterview(_a: WorkflowAction): void {
    this.messageTone = 'info';
    this.message = 'Planification d’entretien : utilisez la page « Offres » → « Voir candidats ».';
    this.router.navigate(['/admin/jobs']);
  }
}
