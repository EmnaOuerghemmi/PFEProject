import { Component, HostListener, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  RecruitmentService, JobOffer, SCORE_BANDS, scoreBandClass,
  APPLICATION_STATUS_META, canTransitionStatus,
} from '../../../core/services/recruitment.service';
import {
  ReportService, HiringRecommendation, DecisionApplicable,
} from '../../../core/services/report.service';
import { PermissionsService } from '../../../core/services/permissions.service';

type Recommandation = HiringRecommendation['recommendation'];
type Filtre = 'TOUS' | Recommandation;

/** Statut que prend la candidature quand on applique la recommandation. */
const STATUT_CIBLE: Partial<Record<Recommandation, string>> = {
  HIRE: 'ACCEPTED', REJECT: 'REJECTED', HOLD: 'ON_HOLD',
};

/**
 * Où en est l'application d'une recommandation :
 * - `possible`   : le bouton « Appliquer » est proposé ;
 * - `appliquee`  : le statut est déjà celui recommandé ;
 * - `impossible` : le parcours l'interdit (ex. reculer d'« Acceptée » à « En réserve ») ;
 * - `sans-objet` : « Évaluation en cours » : pas de recommandation tant que CV, test
 *                  et entretien ne sont pas tous notés — on propose l'étape qui manque.
 */
export type EtatApplication = 'possible' | 'appliquee' | 'impossible' | 'sans-objet';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';

/**
 * Aide à la décision d'embauche.
 *
 * La recommandation réunit CV, test technique et entretien (backend
 * `hiring_decision_service`) avec les seuils du classement. Les ex æquo sont
 * départagés côté serveur, et la raison du départage s'affiche sur la ligne :
 * le RH voit POURQUOI un candidat passe devant un autre au même score.
 */
@Component({
  selector: 'app-decision',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, SelectComponent],
  templateUrl: './decision.component.html',
  styleUrls: ['./decision.component.css'],
})
export class DecisionComponent implements OnInit {
  readonly bands = SCORE_BANDS;

  // ── Recommandations ────────────────────────────────────────────────────────
  jobs: JobOffer[] = [];
  /** Un champ, pas un getter (voir SelectComponent). */
  jobOptions: SelectOption[] = [];
  selectedJobId = '';
  candidates: HiringRecommendation[] = [];
  loadingCandidates = false;
  error = '';
  /** Lignes dépliées (détail des signaux). */
  private expanded = new Set<string>();

  // ── Filtre par recommandation ──────────────────────────────────────────────
  filtre: Filtre = 'TOUS';
  readonly filtres: { value: Filtre; label: string }[] = [
    { value: 'TOUS', label: 'Tous' },
    { value: 'HIRE', label: 'Recruter' },
    { value: 'HOLD', label: 'En réserve' },
    { value: 'REJECT', label: 'Rejeter' },
    { value: 'INCOMPLETE', label: 'Évaluation en cours' },
  ];

  // ── Application d'une recommandation (fenêtre de confirmation) ─────────────
  aConfirmer: HiringRecommendation | null = null;
  messageRefus = '';
  applicationEnCours = false;
  erreurApplication = '';
  succes = '';
  /**
   * Candidature à mettre en avant, venue de `?candidature=` — la page des
   * entretiens y mène après une évaluation (`?offre=` choisit l'offre).
   */
  candidatureCible = '';

  constructor(
    private recruitment: RecruitmentService,
    private reportService: ReportService,
    private route: ActivatedRoute,
    private permissions: PermissionsService,
  ) {}

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const offreDemandee = params.get('offre');
    this.candidatureCible = params.get('candidature') || '';
    this.recruitment.getJobs(1, 100).subscribe({
      next: (res) => {
        this.jobs = res.items;
        this.jobOptions = this.jobs.map((j) => ({ value: j.id, label: j.title }));
        if (!this.selectedJobId && this.jobs.length) {
          const offre = this.jobs.find((j) => j.id === offreDemandee);
          this.selectJob(offre ? offre.id : this.jobs[0].id);
        }
      },
    });
  }

  selectJob(id: string): void {
    this.selectedJobId = id;
    this.loadCandidates();
  }

  loadCandidates(): void {
    if (!this.selectedJobId) return;
    this.loadingCandidates = true;
    this.error = '';
    this.candidates = [];
    this.expanded.clear();
    this.filtre = 'TOUS';
    this.succes = '';
    this.reportService.getJobRecommendations(this.selectedJobId).subscribe({
      next: (res) => {
        this.candidates = res.candidates;
        this.loadingCandidates = false;
        this.mettreEnAvant();
      },
      error: (err) => {
        this.loadingCandidates = false;
        this.error = err?.error?.detail || 'Impossible de charger les recommandations.';
      },
    });
  }

  /** Déplie et montre la candidature demandée, une seule fois. */
  private mettreEnAvant(): void {
    const id = this.candidatureCible;
    if (!id || !this.candidates.some((c) => c.application_id === id)) return;
    this.expanded.add(id);
    // Après le rendu de la ligne.
    setTimeout(() => document.getElementById('candidature-' + id)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  }

  // ── Filtre ─────────────────────────────────────────────────────────────────

  get candidatsAffiches(): HiringRecommendation[] {
    return this.filtre === 'TOUS' ? this.candidates : this.candidates.filter((c) => c.recommendation === this.filtre);
  }

  compte(f: Filtre): number {
    return f === 'TOUS' ? this.candidates.length : this.candidates.filter((c) => c.recommendation === f).length;
  }

  // ── Statut actuel et application ──────────────────────────────────────────

  /** Seul le RH (et l'administrateur) applique une décision ; le recruteur la consulte. */
  get peutDecider(): boolean { return this.permissions.peut('decision', 'write'); }

  statutLabel(statut: string | null): string {
    return (statut && APPLICATION_STATUS_META[statut]?.label) || statut || '—';
  }

  statutCouleur(statut: string | null): string {
    return (statut && APPLICATION_STATUS_META[statut]?.color) || '#7C8A8A';
  }

  etatApplication(c: HiringRecommendation): EtatApplication {
    const cible = STATUT_CIBLE[c.recommendation];
    if (!cible) return 'sans-objet';
    if (c.application_status === cible) return 'appliquee';
    return canTransitionStatus(c.application_status, cible) ? 'possible' : 'impossible';
  }

  demanderApplication(c: HiringRecommendation): void {
    this.aConfirmer = c;
    this.messageRefus = '';
    this.erreurApplication = '';
  }

  @HostListener('document:keydown.escape')
  annulerApplication(): void {
    if (!this.applicationEnCours) this.aConfirmer = null;
  }

  confirmerApplication(): void {
    const c = this.aConfirmer;
    if (!c || this.etatApplication(c) !== 'possible') return;
    const decision = c.recommendation as DecisionApplicable;
    this.applicationEnCours = true;
    this.erreurApplication = '';
    this.reportService.applyDecision(c.application_id, decision, decision === 'REJECT' ? this.messageRefus.trim() : '')
      .subscribe({
        next: (res) => {
          this.applicationEnCours = false;
          c.application_status = res.application_status;
          this.aConfirmer = null;
          const statut = this.statutLabel(res.application_status);
          this.succes = res.email_sent
            ? `${c.candidate_name} : « ${statut} ». Un e-mail lui a été envoyé.`
            : `${c.candidate_name} : « ${statut} ». Le candidat le voit dans son espace.`;
        },
        error: (err) => {
          this.applicationEnCours = false;
          this.erreurApplication = err?.error?.detail || "La décision n'a pas pu être appliquée.";
        },
      });
  }

  isExpanded(c: HiringRecommendation): boolean { return this.expanded.has(c.application_id); }
  toggle(c: HiringRecommendation): void {
    if (!this.expanded.delete(c.application_id)) this.expanded.add(c.application_id);
  }

  // ── Helpers d'affichage ────────────────────────────────────────────────────

  scoreClass(score: number | null | undefined): string { return scoreBandClass(score); }

  /**
   * Dossier incomplet : l'étape qui manque, dans l'ordre du parcours (test,
   * puis entretien), et la page où la lancer.
   */
  etapeManquante(c: HiringRecommendation): { libelle: string; lien: string } {
    if (c.composite.missing.includes('test')) {
      const libelle = c.test.status === 'ENVOYE' || c.test.status === 'EN_COURS' ? 'Suivre le test'
        : c.test.status === 'ABANDONNE' ? 'Renvoyer le test' : 'Envoyer le test';
      return { libelle, lien: '/admin/assessment' };
    }
    const prevu = c.interview.status === 'PENDING' || c.interview.status === 'CONFIRMED';
    return { libelle: prevu ? "Voir l'entretien prévu" : 'Planifier un entretien', lien: '/admin/interviews' };
  }

  /** Le score global n'a de sens que sur les trois notes : partiel, il tromperait. */
  scoreComplet(c: HiringRecommendation): boolean {
    return c.composite.completeness === 3 && c.composite.score !== null;
  }

  recLabel(rec: string): string {
    return ({ HIRE: 'Recruter', HOLD: 'En réserve', REJECT: 'Rejeter', INCOMPLETE: 'Évaluation en cours' } as Record<string, string>)[rec] || rec;
  }
  testLabel(c: HiringRecommendation): string {
    if (c.test.score !== null) return `${Math.round(c.test.score)}`;
    return ({ ENVOYE: 'Envoyé', EN_COURS: 'En cours', ABANDONNE: 'Abandonné' } as Record<string, string>)[c.test.status || ''] || '—';
  }
  interviewLabel(c: HiringRecommendation): string {
    if (c.interview.score !== null) return `${Math.round(c.interview.score)}`;
    return ({ PENDING: 'Invité', CONFIRMED: 'Prévu' } as Record<string, string>)[c.interview.status || ''] || '—';
  }
  trackCandidate(_i: number, c: HiringRecommendation): string { return c.application_id; }
}
