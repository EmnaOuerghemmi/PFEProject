import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { environment } from '../../../environments/environment';

export interface RecruitmentSummary {
  total_jobs: number;
  active_jobs: number;
  total_applications: number;
  applications_by_status: Record<string, number>;
  acceptance_rate: number;
  average_score: number | null;
  top_jobs: { job_offer_id: string; title: string; application_count: number }[];
  generated_at: string;
}

export interface ReportContent {
  narrative: string;
  highlights: string[];
  recommendations: string[];
  generated_by: 'deterministic' | 'claude';
}

export interface ReportSnapshot {
  id: string;
  report_type: string;
  title: string | null;
  data: Partial<RecruitmentSummary> & { report?: ReportContent };
  created_at: string;
}

export interface PaginatedReports {
  items: ReportSnapshot[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
}

/**
 * Recommandation d'embauche : CV, test technique et entretien réunis
 * (backend `hiring_decision_service`). `total_score` reste la note du CV seul.
 */
export interface HiringRecommendation {
  application_id: string;
  candidate_id: string;
  candidate_name: string;
  /** Rang dans l'aide à la décision — pas le rang du CV. */
  decision_rank: number;
  /** INCOMPLETE : pas de recommandation tant que CV, test et entretien ne sont pas tous notés. */
  recommendation: 'HIRE' | 'HOLD' | 'REJECT' | 'INCOMPLETE';
  confidence: 'high' | 'medium' | 'low';
  /** Verdict chiffré, en une phrase. */
  rationale: string;
  /** Points forts, chacun vérifiable dans le dossier. */
  strengths: string[];
  /** Points de vigilance — jamais soustraits de la note. */
  warnings: string[];
  /** L'action la plus utile maintenant. */
  next_step: string;
  /** Tout ce qui précède, rédigé en un paragraphe : « Je propose de…, car… ». */
  explanation: string;
  composite: {
    score: number | null;
    /** 1, 2 ou 3 volets évalués (CV, test, entretien). */
    completeness: number;
    available: string[];
    missing: string[];
    band: string;
  };
  cv: {
    score: number; skills_score: number; experience_score: number; education_score: number;
    matched_skills: number; missing_skills: number;
  };
  test: {
    status: string | null; score: number | null;
    hard_success_rate: number | null; hard_total: number;
    anomaly_count: number; overrun_questions: number;
  };
  interview: { score: number | null; status: string | null; has_notes: boolean };
  expected_salary: number | null;
  /** Présent quand d'autres candidats ont le même score : le critère qui les sépare. */
  tie: { group_size: number; score: number; decided_by: string | null; explanation: string } | null;
  total_score: number;
  /** Statut actuel de la candidature (voir APPLICATION_STATUS_META). */
  application_status: string | null;
}

/** Recommandations qui deviennent un statut quand on les applique. */
export type DecisionApplicable = 'HIRE' | 'REJECT' | 'HOLD';

export interface JobRecommendations {
  job_offer_id: string;
  /** Seuils 85 / 60 / 30 — les mêmes que la légende du classement. */
  bands: { excellent: number; good: number; average: number };
  candidates: HiringRecommendation[];
}


@Injectable({ providedIn: 'root' })
export class ReportService {
  constructor(private api: ApiService) {}

  // ── Analytics live ────────────────────────────────────────────────────────

  getSummary(): Observable<RecruitmentSummary> {
    return this.api.get<RecruitmentSummary>('reports/recruitment-summary');
  }

  // ── CRUD des rapports archivés ────────────────────────────────────────────

  listReports(page = 1, pageSize = 10): Observable<PaginatedReports> {
    return this.api.get<PaginatedReports>('reports', { page, page_size: pageSize });
  }

  getReport(id: string): Observable<ReportSnapshot> {
    return this.api.get<ReportSnapshot>(`reports/${id}`);
  }

  /** Génère un rapport via l'agent de reporting et l'archive. */
  generateReport(title?: string): Observable<ReportSnapshot> {
    return this.api.post<ReportSnapshot>('reports/snapshot', title ? { title } : {});
  }

  renameReport(id: string, title: string): Observable<ReportSnapshot> {
    return this.api.patch<ReportSnapshot>(`reports/${id}`, { title });
  }

  deleteReport(id: string): Observable<void> {
    return this.api.delete<void>(`reports/${id}`);
  }

  /** Télécharge le PDF du rapport (blob). */
  downloadPdf(id: string): Observable<Blob> {
    return this.api.http.get(`${environment.apiUrl}/reports/${id}/pdf`, {
      responseType: 'blob',
    });
  }

  // ── Décision ──────────────────────────────────────────────────────────────

  getRecommendation(applicationId: string): Observable<HiringRecommendation> {
    return this.api.get<HiringRecommendation>(`decision/applications/${applicationId}/recommendation`);
  }

  /**
   * La recommandation devient le statut de la candidature. Rejet et réserve
   * envoient un e-mail au candidat ; la réserve l'inscrit aussi au vivier.
   */
  applyDecision(applicationId: string, decision: DecisionApplicable, message = ''):
      Observable<{ application_id: string; application_status: string; email_sent: boolean }> {
    return this.api.post(`decision/applications/${applicationId}/apply`, { decision, message });
  }

  /** Toutes les candidatures ouvertes d'une offre, classées et départagées. */
  getJobRecommendations(jobId: string): Observable<JobRecommendations> {
    return this.api.get<JobRecommendations>(`decision/jobs/${jobId}/recommendations`);
  }
}
