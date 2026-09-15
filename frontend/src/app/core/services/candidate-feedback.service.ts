import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

/**
 * Le détail de sa propre candidature, côté candidat.
 *
 * Deux champs sont **optionnels au sens fort** : `test_score` et
 * `interview_feedback` sont ABSENTS de la réponse tant que le recrutement n'a
 * pas ouvert le partage — pas à `null`.
 *
 * L'écran doit refléter cette absence telle quelle : pas de section grisée, pas
 * de « non communiqué ». Signaler qu'une note existe mais n'est pas partagée
 * reviendrait à pousser le candidat à la réclamer, et le recruteur à se
 * justifier de ne pas l'avoir donnée.
 */

export interface Observation {
  sujet: string;
  constat: string;
}

export interface ScoreWeights {
  skills?: number | null;
  experience?: number | null;
  education?: number | null;
}

export interface ApplicationScoreDetail {
  application_id: string;
  job_offer_id: string;
  job_title: string;
  job_description: string;
  job_required_skills: string[];
  job_required_experience_years?: number | null;
  job_required_education_level?: string | null;
  job_salary_min?: number | null;
  job_salary_max?: number | null;
  job_work_mode?: string | null;
  job_contract_types: string[];
  applied_at: string;
  status: string;

  /** Faux tant que l'analyse du CV n'a pas tourné — elle est lancée au dépôt. */
  analysis_ready: boolean;

  score?: number | null;
  band?: 'forte' | 'bonne' | 'partielle' | 'faible' | null;
  summary?: string | null;
  weights?: ScoreWeights | null;

  skills_matched: string[];
  skills_missing: string[];
  skills_required: string[];

  experience_detected_years?: number | null;
  experience_required_years?: number | null;
  education_detected?: string | null;
  education_required?: string | null;

  observations: Observation[];
  advice: string[];

  /** Présents UNIQUEMENT si le recrutement a ouvert le partage. */
  test_score?: number;
  interview_feedback?: string;
}

/** État du partage, côté back-office. */
export interface CandidateVisibilityState {
  application_id: string;
  test_score_visible: boolean;
  interview_feedback_visible: boolean;
  candidate_feedback?: string | null;
  /** Faux quand aucune note de test n'existe : ouvrir ne montrerait rien. */
  has_test_score: boolean;
}

export interface CandidateVisibilityUpdate {
  test_score_visible?: boolean;
  interview_feedback_visible?: boolean;
  candidate_feedback?: string | null;
}

@Injectable({ providedIn: 'root' })
export class CandidateFeedbackService {
  private api = inject(ApiService);

  /** Réservé au propriétaire de la candidature — le serveur le vérifie. */
  scoreDetail(applicationId: string): Observable<ApplicationScoreDetail> {
    return this.api.get<ApplicationScoreDetail>(
      `recruitment/my-applications/${applicationId}/score-detail`,
    );
  }

  // ── Back-office ────────────────────────────────────────────────────────────

  visibility(applicationId: string): Observable<CandidateVisibilityState> {
    return this.api.get<CandidateVisibilityState>(
      `assessment/applications/${applicationId}/visibility`,
    );
  }

  setVisibility(applicationId: string, body: CandidateVisibilityUpdate):
      Observable<CandidateVisibilityState> {
    return this.api.post<CandidateVisibilityState>(
      `assessment/applications/${applicationId}/visibility`, body,
    );
  }
}
