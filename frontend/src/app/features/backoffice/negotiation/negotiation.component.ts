import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  RecruitmentService, JobOffer, CandidateRanking, NegotiationAnalysis,
} from '../../../core/services/recruitment.service';

@Component({
  selector: 'app-negotiation',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './negotiation.component.html',
  styleUrls: ['./negotiation.component.css'],
})
export class NegotiationComponent implements OnInit {
  jobs: JobOffer[] = [];
  selectedJobId = '';

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

  onJobChange(): void {
    this.selectedApplicationId = '';
    this.candidates = [];
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
        if (this.candidates.length) {
          this.selectedApplicationId = this.candidates[0].application_id;
          this.surCandidatChange();
        }
      },
      error: () => {
        this.loadingCandidates = false;
        this.candidates = [];
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

  verdictIcon(v: string): string {
    return ({
      acceptable: '✅', counter_offer: '↔️', stretch: '🌟', negotiation_required: '⚠️',
    } as Record<string, string>)[v] || '🔔';
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

  /** Libellé de la provenance du nombre d'années d'expérience. */
  experienceOrigin(): string {
    switch (this.result?.experience_source) {
      case 'candidate_score': return 'chiffre du modèle de classement';
      case 'cv': return 'extraite du CV';
      default: return 'CV non analysé — valeur du poste utilisée';
    }
  }

  /** Décomposition du score, dans l'ordre décroissant de pondération. */
  scoreComponents(): { label: string; value: number; weight: string }[] {
    const b = this.result?.score_breakdown;
    if (!b) return [];
    return [
      { label: 'Expérience', value: b.experience, weight: '30 %' },
      { label: 'Matching CV', value: b.matching ?? b.experience, weight: '30 %' },
      { label: 'Position marché', value: b.market_position, weight: '20 %' },
      { label: 'Confort budget', value: b.budget, weight: '20 %' },
    ];
  }

  signalLabel(s: string): string {
    return ({
      above_market: 'Demande au-dessus du marché',
      below_market: 'Candidat potentiellement sous-payé',
      budget_below_market: 'Budget de l’offre sous le marché',
      top_of_range: 'Haut de fourchette atteint',
      overqualified: 'Expérience au-delà du requis',
      underqualified: 'Profil en deçà du requis',
    } as Record<string, string>)[s] || s;
  }

  signalTone(s: string): string {
    return ({
      above_market: 'warn',
      below_market: 'warn',
      budget_below_market: 'danger',
      top_of_range: 'info',
      overqualified: 'success',
      underqualified: 'warn',
    } as Record<string, string>)[s] || 'info';
  }
}
