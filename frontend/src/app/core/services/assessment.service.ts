import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

/**
 * Test technique : vivier, passage, résultats.
 *
 * Le service reflète la coupure du backend. Les méthodes `public*` n'exigent
 * aucune authentification et ne reçoivent jamais de bonne réponse ni de note :
 * le candidat n'apprend rien du barème pendant qu'il compose. Tout le reste
 * est réservé au RH.
 */

export type QuestionDifficulty = 'FACILE' | 'MOYENNE' | 'DIFFICILE';
export type QuestionKind = 'QCM_UNIQUE' | 'QCM_MULTIPLE' | 'REPONSE_COURTE';
export type QuestionStatus = 'GENEREE' | 'VALIDEE' | 'ACTIVE' | 'RETIREE';
export type SessionStatus = 'ENVOYE' | 'EN_COURS' | 'TERMINE' | 'EXPIRE' | 'ABANDONNE';
/** Quatre issues là où un booléen suffirait au calcul — « passée » et
 *  « fausse » valent zéro, mais ne disent pas la même chose du candidat. */
export type AnswerOutcome = 'CORRECTE' | 'FAUSSE' | 'PASSEE' | 'NON_ATTEINTE';

export const DIFFICULTY_LABELS: Record<QuestionDifficulty, string> = {
  FACILE: 'Facile', MOYENNE: 'Moyenne', DIFFICILE: 'Difficile',
};

export const OUTCOME_LABELS: Record<AnswerOutcome, string> = {
  CORRECTE: 'Correcte', FAUSSE: 'Fausse',
  PASSEE: 'Passée', NON_ATTEINTE: 'Non atteinte',
};

export interface TestQuestion {
  id: string;
  job_offer_id: string;
  statement: string;
  options: string[] | null;
  correct_answer: string[];
  explanation: string | null;
  difficulty: QuestionDifficulty;
  kind: QuestionKind;
  status: QuestionStatus;
  expected_seconds: number;
  skill_tag: string | null;
  generated_by: string | null;
  times_served: number;
  times_correct: number;
  times_skipped: number;
  success_rate: number | null;
  created_at: string;
}

/** Les deux compteurs que l'écran de sélection doit montrer en permanence. */
export interface BankCoverage {
  total: number;
  par_difficulte: Record<string, number>;
  gabarit: Record<string, number>;
  competences_couvertes: string[];
  competences_manquantes: string[];
}

export interface TestPreparation {
  questions: TestQuestion[];
  coverage: BankCoverage;
}

export interface GenerationReport {
  generated: number;
  rejected: number;
  reasons: string[];
}

/** Vue candidat : ni bonne réponse, ni explication, ni budget de temps. */
export interface PublicQuestion {
  position: number;
  total: number;
  statement: string;
  options: string[];
  kind: QuestionKind;
  /** Temps GLOBAL restant — seule information de temps donnée au candidat. */
  seconds_remaining: number;
}

export interface PublicTestIntro {
  job_title: string;
  question_count: number;
  duration_minutes: number;
  status: SessionStatus;
  already_submitted: boolean;
  link_expired: boolean;
}

export interface SubmitAnswerResponse {
  accepted: boolean;
  next_question: PublicQuestion | null;
  finished: boolean;
}

export interface AnswerReview {
  position: number;
  statement: string;
  options: string[] | null;
  given_answer: string[] | null;
  correct_answer: string[];
  outcome: AnswerOutcome;
  difficulty: QuestionDifficulty;
  skill_tag: string | null;
  elapsed_seconds: number | null;
  expected_seconds: number;
  overrun_seconds: number;
}

export interface SkillBreakdown {
  skill: string;
  asked: number;
  correct: number;
  rate: number;
}

export interface TestSessionDetail {
  id: string;
  application_id: string;
  status: SessionStatus;
  question_count: number;
  duration_minutes: number;
  sent_at: string;
  started_at: string | null;
  submitted_at: string | null;
  score: number | null;
  correct_count: number | null;
  total_overrun_seconds: number;
  overrun_question_count: number;
  anomaly_flags: Array<Record<string, any>> | null;
  outcome_counts: Record<string, number>;
  by_skill: SkillBreakdown[];
  answers: AnswerReview[];
}

export interface CriterionSuggestion {
  score: number | null;
  justification: string;
}

/** Proposition du modèle — jamais une décision. */
export interface InterviewSuggestion {
  available: boolean;
  reason?: string | null;
  model?: string | null;
  suggested_at?: string | null;
  criteria: Record<string, CriterionSuggestion>;
  overall: number | null;
  summary: string;
}

export interface CompositeScore {
  score: number | null;
  /** 1, 2 ou 3 volets. Deux complétudes différentes ne se comparent pas. */
  completeness: number;
  available: string[];
  missing: string[];
  band: string;
  uncertainty: number;
  breakdown: Record<string, { value: number; weight: number }>;
}

export interface CandidateEvaluation {
  application_id: string;
  cv_score: number | null;
  test_score: number | null;
  interview_score: number | null;
  interview_notes: string | null;
  interview_ai_suggestion: Record<string, any> | null;
  composite: CompositeScore;
}

@Injectable({ providedIn: 'root' })
export class AssessmentService {
  private api = inject(ApiService);

  // ── Candidat, par jeton — aucune authentification ──────────────────────────

  publicIntro(token: string): Observable<PublicTestIntro> {
    return this.api.get<PublicTestIntro>(`assessment/public/${token}`);
  }

  /** Démarre le chronomètre et sert la première question. */
  publicStart(token: string): Observable<SubmitAnswerResponse> {
    return this.api.post<SubmitAnswerResponse>(`assessment/public/${token}/start`, {});
  }

  /**
   * `answer = null` vaut « Passer » — compté comme une erreur.
   * Aucune durée n'est transmise : le serveur mesure le temps lui-même.
   */
  publicAnswer(token: string, position: number, answer: string[] | null):
      Observable<SubmitAnswerResponse> {
    return this.api.post<SubmitAnswerResponse>(
      `assessment/public/${token}/answer`, { position, answer },
    );
  }

  publicFinish(token: string): Observable<{ finished: boolean; message: string }> {
    return this.api.post<{ finished: boolean; message: string }>(
      `assessment/public/${token}/finish`, {},
    );
  }

  // ── Vivier (RH) ────────────────────────────────────────────────────────────

  listQuestions(jobId: string, status?: QuestionStatus): Observable<TestQuestion[]> {
    const suffixe = status ? `?status=${status}` : '';
    return this.api.get<TestQuestion[]>(`assessment/jobs/${jobId}/questions${suffixe}`);
  }

  generateBank(jobId: string, count = 30): Observable<GenerationReport> {
    return this.api.post<GenerationReport>(
      `assessment/jobs/${jobId}/questions/generate?count=${count}`, {},
    );
  }

  createQuestion(jobId: string, body: Partial<TestQuestion>): Observable<TestQuestion> {
    return this.api.post<TestQuestion>(`assessment/jobs/${jobId}/questions`, body);
  }

  updateQuestion(questionId: string, body: Partial<TestQuestion>): Observable<TestQuestion> {
    return this.api.patch<TestQuestion>(`assessment/questions/${questionId}`, body);
  }

  setQuestionStatus(questionId: string, status: QuestionStatus): Observable<TestQuestion> {
    return this.api.post<TestQuestion>(
      `assessment/questions/${questionId}/status?new_status=${status}`, {},
    );
  }

  activateBank(jobId: string): Observable<{ activated: number }> {
    return this.api.post<{ activated: number }>(
      `assessment/jobs/${jobId}/questions/activate`, {},
    );
  }

  // ── Préparation, envoi, résultats (RH) ─────────────────────────────────────

  prepareTest(applicationId: string, count = 12): Observable<TestPreparation> {
    return this.api.get<TestPreparation>(
      `assessment/applications/${applicationId}/prepare?count=${count}`,
    );
  }

  sendTest(applicationId: string, questionIds: string[], durationMinutes = 20):
      Observable<unknown> {
    return this.api.post(`assessment/applications/${applicationId}/send`, {
      question_ids: questionIds, duration_minutes: durationMinutes,
    });
  }

  sessionDetail(applicationId: string): Observable<TestSessionDetail> {
    return this.api.get<TestSessionDetail>(
      `assessment/applications/${applicationId}/session`,
    );
  }

  // ── Entretien et score composite (RH) ──────────────────────────────────────

  evaluation(applicationId: string): Observable<CandidateEvaluation> {
    return this.api.get<CandidateEvaluation>(
      `assessment/applications/${applicationId}/evaluation`,
    );
  }

  saveInterviewNotes(applicationId: string, notes: string): Observable<CandidateEvaluation> {
    return this.api.post<CandidateEvaluation>(
      `assessment/applications/${applicationId}/interview/notes`, { notes },
    );
  }

  suggestInterview(applicationId: string, notes: string): Observable<InterviewSuggestion> {
    return this.api.post<InterviewSuggestion>(
      `assessment/applications/${applicationId}/interview/suggest`, { notes },
    );
  }

  setInterviewScore(applicationId: string, score: number | null, notes?: string):
      Observable<CandidateEvaluation> {
    return this.api.post<CandidateEvaluation>(
      `assessment/applications/${applicationId}/interview/score`,
      { interview_score: score, notes: notes ?? null },
    );
  }
}
