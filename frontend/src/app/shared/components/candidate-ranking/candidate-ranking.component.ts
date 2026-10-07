import { Component, Input, OnInit, OnChanges, SimpleChanges, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RecruitmentService, CandidateRanking, scoreBandClass } from '../../../core/services/recruitment.service';
import { PaginationComponent } from '../pagination/pagination.component';

export interface WorkflowAction {
  applicationId: string;
  candidateId: string;
  score: number;
}

@Component({
  selector: 'app-candidate-ranking',
  standalone: true,
  imports: [CommonModule, PaginationComponent],
  templateUrl: './candidate-ranking.component.html',
  styleUrls: ['./candidate-ranking.component.css']
})
export class CandidateRankingComponent implements OnInit, OnChanges {
  @Input() jobId: string = '';
  /** Bump this number from the parent to force a reload (e.g. after scheduling
   *  an interview, so the button state refreshes). */
  @Input() refreshTrigger: number = 0;

  // Pas de sortie `startNegotiation` : la négociation ne se lance plus depuis
  // le classement. Elle suppose une évaluation préalable — test rendu ou
  // entretien passé — qui n'a pas encore eu lieu à ce stade.
  @Output() scheduleInterview = new EventEmitter<WorkflowAction>();
  @Output() rejectCandidate   = new EventEmitter<WorkflowAction>();
  @Output() sendTest          = new EventEmitter<WorkflowAction>();

  candidates: CandidateRanking[] = [];
  isLoading = true;

  /** Pagination : 4 cartes par page, taille fixe. */
  readonly pageSize = 4;
  currentPage = 1;
  pagedCandidates: CandidateRanking[] = [];

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.candidates.length / this.pageSize));
  }

  /** Position dans le classement COMPLET : rang et médailles ne repartent pas à 1 à chaque page. */
  globalIndex(i: number): number {
    return (this.currentPage - 1) * this.pageSize + i;
  }

  goToPage(page: number) {
    this.currentPage = page;
    const start = (page - 1) * this.pageSize;
    this.pagedCandidates = this.candidates.slice(start, start + this.pageSize);
  }
  /** IDs (application_id) of the cards currently expanded to show details. */
  private expandedIds = new Set<string>();

  constructor(private recruitment: RecruitmentService) {}

  ngOnInit() {
    this.loadRanking();
  }

  ngOnChanges(changes: SimpleChanges) {
    // Re-fetch when the selected offer changes (user clicks another job) OR
    // when the parent signals a manual refresh.
    const jobChanged = changes['jobId'] && !changes['jobId'].firstChange;
    const refreshed = changes['refreshTrigger'] && !changes['refreshTrigger'].firstChange;
    if (jobChanged) this.currentPage = 1;
    if ((jobChanged || refreshed) && this.jobId) {
      this.candidates = [];
      this.pagedCandidates = [];
      this.isLoading = true;
      this.loadRanking();
    }
  }

  loadRanking() {
    if (!this.jobId) { this.isLoading = false; return; }
    this.recruitment.getRankedCandidates(this.jobId).subscribe({
      next: (response) => {
        this.candidates = response.ranking;
        // Nouvelle offre : retour en page 1. Simple rafraîchissement (après un
        // entretien planifié) : on reste sur la page, bornée si la liste a rétréci.
        this.goToPage(Math.min(this.currentPage, this.totalPages));
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });
  }

  isExpanded(c: CandidateRanking): boolean {
    return this.expandedIds.has(c.application_id);
  }

  toggleExpanded(c: CandidateRanking) {
    if (this.expandedIds.has(c.application_id)) {
      this.expandedIds.delete(c.application_id);
    } else {
      this.expandedIds.add(c.application_id);
    }
  }

  /** Seuils partagés avec l'aide à la décision (`SCORE_BANDS`). */
  getScoreClass(score: number): string {
    return scoreBandClass(score);
  }

  getScoreLabel(score: number): string {
    if (score >= 85) return '🟢 Excellent';
    if (score >= 60) return '🟡 Bon';
    if (score >= 30) return '🟠 Moyen';
    return '🔴 Faible';
  }

  onScheduleInterview(c: CandidateRanking) {
    if (this.hasActiveInterview(c)) return;
    this.scheduleInterview.emit({ applicationId: c.application_id, candidateId: c.candidate_id, score: c.total_score });
  }

  onReject(c: CandidateRanking) {
    this.rejectCandidate.emit({ applicationId: c.application_id, candidateId: c.candidate_id, score: c.total_score });
  }

  onSendTest(c: CandidateRanking) {
    if (!c.can_send_test) return;
    this.sendTest.emit({ applicationId: c.application_id, candidateId: c.candidate_id, score: c.total_score });
  }

  // ── État du test technique ──
  // L'éligibilité vient du serveur : aucun seuil de score n'est écrit ici.

  testEnvoye(c: CandidateRanking): boolean {
    return !!c.test_status;
  }

  testTermine(c: CandidateRanking): boolean {
    return c.test_status === 'TERMINE' || c.test_status === 'EXPIRE';
  }

  /** Un test parti dont on attend encore le résultat. */
  testEnAttente(c: CandidateRanking): boolean {
    return c.test_status === 'ENVOYE' || c.test_status === 'EN_COURS';
  }

  testBadgeLabel(c: CandidateRanking): string {
    switch (c.test_status) {
      case 'ENVOYE':    return '📨 Test envoyé';
      case 'EN_COURS':  return '✍️ Test en cours';
      case 'TERMINE':   return c.test_score != null
                          ? `📝 Test : ${c.test_score}/100`
                          : '📝 Test passé';
      case 'EXPIRE':    return '⏱️ Test — temps écoulé';
      case 'ABANDONNE': return '⚠️ Lien de test expiré';
      default:          return '';
    }
  }

  /**
   * Vrai quand l'entretien devrait attendre le test. L'écran atténue alors le
   * bouton — il ne le retire pas : rencontrer un candidat reste une décision
   * humaine, et le test l'informe sans la prendre.
   */
  entretienPremature(c: CandidateRanking): boolean {
    return c.can_schedule_interview === false;
  }

  /** Infobulle du bouton d'entretien, selon ce qui le retient. */
  interviewTitle(c: CandidateRanking): string {
    if (this.isInterviewConfirmed(c)) {
      return 'Entretien déjà confirmé — annulez-le depuis Entretiens pour replanifier';
    }
    if (this.isInterviewPassed(c)) {
      return 'Le premier entretien a eu lieu — planifier un nouvel entretien avec ce candidat';
    }
    if (this.isInterviewPending(c)) {
      return 'Invitation déjà envoyée — en attente du choix du candidat';
    }
    if (this.entretienPremature(c)) {
      return "Le test technique n'a pas encore été rendu — vous pouvez tout de même planifier un entretien";
    }
    return 'Planifier un entretien avec ce candidat';
  }

  // ── Interview state helpers ──
  /**
   * Un entretien qui retient encore le bouton : une invitation en attente, ou
   * un entretien confirmé qui n'a PAS encore eu lieu. Une fois passé, il reste
   * au dossier mais un second entretien est possible.
   */
  hasActiveInterview(c: CandidateRanking): boolean {
    return c.interview_status === 'PENDING' || this.isInterviewConfirmed(c);
  }

  /** Confirmé et à venir (ou en cours). */
  isInterviewConfirmed(c: CandidateRanking): boolean {
    return c.interview_status === 'CONFIRMED' && !c.interview_ended;
  }

  /** Confirmé et déjà passé. */
  isInterviewPassed(c: CandidateRanking): boolean {
    return c.interview_status === 'CONFIRMED' && !!c.interview_ended;
  }

  isInterviewPending(c: CandidateRanking): boolean {
    return c.interview_status === 'PENDING';
  }

  interviewBadgeLabel(c: CandidateRanking): string {
    if (this.isInterviewConfirmed(c)) return '✓ Entretien confirmé';
    if (this.isInterviewPassed(c))    return '✓ Entretien passé';
    if (this.isInterviewPending(c))   return '⏳ Invitation envoyée';
    return '';
  }
}
