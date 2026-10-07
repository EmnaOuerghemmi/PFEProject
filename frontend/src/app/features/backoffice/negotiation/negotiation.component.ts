import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';
import {
  RecruitmentService, JobOffer, CandidateRanking, NegotiationAnalysis, NegotiationExplanationLine,
} from '../../../core/services/recruitment.service';

@Component({
  selector: 'app-negotiation',
  standalone: true,
  imports: [CommonModule, FormsModule, SelectComponent],
  templateUrl: './negotiation.component.html',
  styleUrls: ['./negotiation.component.css'],
})
export class NegotiationComponent implements OnInit {
  jobs: JobOffer[] = [];
  selectedJobId = '';
  /** Options des sélecteurs — des champs remplis au chargement, pas des getters. */
  jobOptions: SelectOption[] = [];
  candidateOptions: SelectOption[] = [];

  candidates: CandidateRanking[] = [];
  loadingCandidates = false;
  selectedApplicationId = '';

  requestedSalary: number | null = null;
  /** Fourchette budgétaire du poste : c'est le MAXIMUM qui sert de seuil. */
  baseSalary: number | null = null;
  baseSalaryMax: number | null = null;

  analyzing = false;
  error = '';
  result: NegotiationAnalysis | null = null;

  constructor(private recruitment: RecruitmentService) {}

  ngOnInit(): void {
    this.recruitment.getJobs(1, 100).subscribe({
      next: res => {
        this.jobs = res.items;
        this.jobOptions = this.jobs.map(j => ({ value: j.id, label: j.title }));
        if (!this.selectedJobId && this.jobs.length) {
          this.selectedJobId = this.jobs[0].id;
          this.onJobChange();
        }
      },
    });
  }

  get selectedJob(): JobOffer | undefined {
    return this.jobs.find(j => j.id === this.selectedJobId);
  }

  get selectedCandidate(): CandidateRanking | undefined {
    return this.candidates.find(c => c.application_id === this.selectedApplicationId);
  }

  choisirOffre(id: string): void {
    this.selectedJobId = id;
    this.onJobChange();
  }

  choisirCandidat(id: string): void {
    this.selectedApplicationId = id;
    this.surCandidatChange();
  }

  onJobChange(): void {
    this.selectedApplicationId = '';
    this.candidates = [];
    this.candidateOptions = [];
    this.result = null;
    this.error = '';

    const job = this.selectedJob;
    this.baseSalary = job?.salary_min ?? null;
    this.baseSalaryMax = job?.salary_max ?? null;

    if (!this.selectedJobId) return;
    this.loadingCandidates = true;
    this.recruitment.getRankedCandidates(this.selectedJobId).subscribe({
      next: res => {
        this.loadingCandidates = false;
        this.candidates = res.ranking || [];
        this.candidateOptions = this.candidates.map(c => ({
          value: c.application_id,
          label: `${c.candidate_name || '#' + c.candidate_id.slice(0, 8)} — score ${Math.round(c.total_score)}/100`,
        }));
        if (this.candidates.length) {
          this.selectedApplicationId = this.candidates[0].application_id;
          this.surCandidatChange();
        }
      },
      error: () => {
        this.loadingCandidates = false;
        this.candidates = [];
        this.candidateOptions = [];
      },
    });
  }

  /**
   * Reprend la prétention que le candidat a annoncée au dépôt de sa
   * candidature. Le RH n'a plus à la ressaisir de mémoire — et quand le
   * candidat n'a pas répondu, le champ reste libre.
   */
  surCandidatChange(): void {
    const annonce = this.selectedCandidate?.expected_salary;
    this.requestedSalary = annonce != null && annonce > 0 ? annonce : null;
    this.result = null;
  }

  /** Vrai quand le montant affiché vient du candidat et n'a pas été modifié. */
  get pretentionDuCandidat(): boolean {
    const annonce = this.selectedCandidate?.expected_salary;
    return annonce != null && annonce > 0 && this.requestedSalary === annonce;
  }

  analyze(): void {
    if (!this.selectedApplicationId || !this.requestedSalary || this.requestedSalary <= 0) return;

    this.analyzing = true;
    this.error = '';
    this.result = null;

    this.recruitment
      .negotiationAnalysis(this.selectedApplicationId, this.requestedSalary, this.baseSalary, this.baseSalaryMax)
      .subscribe({
        next: res => {
          this.analyzing = false;
          this.result = res;
        },
        error: err => {
          this.analyzing = false;
          this.error = err?.error?.detail || "L'analyse a échoué. Réessayez.";
        },
      });
  }

  verdictLabel(v: string): string {
    return ({
      acceptable: 'Demande acceptable',
      counter_offer: 'Contre-proposition',
      stretch: 'Effort exceptionnel',
      negotiation_required: 'Négociation nécessaire',
    } as Record<string, string>)[v] || v;
  }

  verdictTone(v: string): string {
    return ({
      acceptable: 'success', counter_offer: 'warn', stretch: 'warn', negotiation_required: 'danger',
    } as Record<string, string>)[v] || 'info';
  }

  /** Tonalité du dépassement budgétaire : 0 TND est une bonne nouvelle. */
  overrunTone(): string {
    return (this.result?.budget_overrun ?? 0) > 0 ? 'danger' : 'success';
  }

  // ── Lecture de l'explication : chaque fait rangé à sa place ──────────────

  /** L'action à mener — affichée en tête, sous le montant recommandé. */
  get recommendationLine(): NegotiationExplanationLine | undefined {
    return this.result?.explanation_lines.find(l => l.kind === 'recommendation');
  }

  /** Ce qui doit retenir l'attention. Les simples faits sont déjà en chiffres. */
  get alerts(): NegotiationExplanationLine[] {
    return this.result?.explanation_lines.filter(l => l.kind === 'alert') ?? [];
  }

  /** Faux quand le CV n'a pas été analysé : l'expérience est celle du poste. */
  experienceMeasured(): boolean {
    return this.result?.experience_source !== 'job_requirement';
  }

  /** Provenance du nombre d'années d'expérience. */
  experienceOrigin(): string {
    switch (this.result?.experience_source) {
      case 'candidate_score': return 'selon le classement';
      case 'cv': return 'extraite du CV';
      default: return 'non mesurée — valeur du poste';
    }
  }

  /** Montant au format français : « 1 300 », comme dans les phrases du backend. */
  tnd(v: number | null | undefined): string {
    return v == null ? '—' : Math.round(v).toLocaleString('fr-FR');
  }

  /** « 1 an », « 1,5 an », « 3 ans ». */
  annees(v: number | null | undefined): string {
    if (v == null) return '—';
    const arrondi = Math.round(v * 10) / 10;
    const texte = Number.isInteger(arrondi) ? `${arrondi}` : `${arrondi}`.replace('.', ',');
    return `${texte} ${Math.abs(arrondi) < 2 ? 'an' : 'ans'}`;
  }

  gapLabel(gap: number): string {
    if (gap === 0) return 'conforme au niveau demandé';
    return gap > 0 ? `${this.annees(gap)} de plus que requis` : `${this.annees(-gap)} de moins que requis`;
  }

  /** Décomposition du score, dans l'ordre décroissant de pondération. */
  scoreComponents(): { label: string; value: number; weight: string; unmeasured: boolean }[] {
    const b = this.result?.score_breakdown;
    if (!b) return [];
    return [
      // Sans analyse du CV, ce 100 vient de l'expérience du poste : signalé.
      { label: 'Expérience', value: b.experience, weight: '30 %', unmeasured: !this.experienceMeasured() },
      { label: 'Matching CV', value: b.matching ?? b.experience, weight: '30 %', unmeasured: false },
      { label: 'Position marché', value: b.market_position, weight: '20 %', unmeasured: false },
      { label: 'Confort budget', value: b.budget, weight: '20 %', unmeasured: false },
    ];
  }
}
