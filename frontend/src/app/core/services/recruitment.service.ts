import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService } from './api.service';
import { environment } from '../../../environments/environment';

export type WorkMode = 'ON_SITE' | 'HYBRID' | 'REMOTE';
export type ContractType = 'CDI' | 'CDD' | 'SIVP' | 'STAGE' | 'FREELANCE';
export type JobStatus = 'DRAFT' | 'PUBLISHED' | 'CLOSED';

/** Libellés affichables — source unique pour le backoffice et le frontoffice. */
export const WORK_MODE_LABELS: Record<WorkMode, string> = {
  ON_SITE: 'Sur site',
  HYBRID: 'Hybride',
  REMOTE: 'Télétravail',
};

export const CONTRACT_TYPE_LABELS: Record<ContractType, string> = {
  CDI: 'CDI',
  CDD: 'CDD',
  SIVP: 'SIVP',
  STAGE: 'Stage',
  FREELANCE: 'Freelance',
};

/**
 * Libellé lisible des types de contrat d'une offre.
 *
 * Une offre peut en accepter plusieurs (« SIVP ou CDD ») : la fonction rend
 * une chaîne unique prête à afficher. Elle vit ici, à côté des libellés, pour
 * que les quatre écrans qui l'utilisaient chacun de leur côté partagent la
 * même formulation.
 */
export function contractTypesLabel(types: ContractType[] | null | undefined): string {
  return (types ?? []).map(t => CONTRACT_TYPE_LABELS[t] ?? t).join(' · ');
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  DRAFT: 'Brouillon',
  PUBLISHED: 'Publiée',
  CLOSED: 'Fermée',
};

/**
 * Statuts de candidature — miroir du vocabulaire backend
 * (`app/models/application_status.py`). Trois composants en tenaient chacun
 * une copie, et les trois divergeaient : l'une inventait `REVIEWING`,
 * `SHORTLISTED` et `OFFER` que le serveur ne produit pas, les deux autres
 * ignoraient les statuts de test.
 *
 * Une couleur accompagne le libellé : elle sert aux légendes du tableau de
 * bord, et deux composants ne doivent pas colorer le même statut autrement.
 */
export const APPLICATION_STATUS_META: Record<string, { label: string; color: string }> = {
  PENDING:             { label: 'En attente',        color: '#D7903A' },
  REVIEWED:            { label: 'Examinée',          color: '#5687B8' },
  TEST_SENT:           { label: 'Test envoyé',       color: '#94A3B8' },
  EN_TEST:             { label: 'Test en cours',     color: '#6B4E95' },
  TEST_DONE:           { label: 'Test passé',        color: '#8E6FB8' },
  INTERVIEW_SCHEDULED: { label: 'Entretien planifié', color: '#22D3EE' },
  NEGOTIATION:         { label: 'Négociation',       color: '#0EA5E9' },
  ON_HOLD:             { label: 'En réserve',        color: '#B8860B' },
  ACCEPTED:            { label: 'Acceptée',          color: '#3DA76F' },
  HIRED:               { label: 'Recrutée',          color: '#10B981' },
  REJECTED:            { label: 'Rejetée',           color: '#D45B5B' },
  WITHDRAWN:           { label: 'Retirée par le candidat', color: '#7C8A8A' },
};

/**
 * Seuils de lecture d'un score — UNE grille pour tout l'écran RH : légende du
 * classement, pastilles et aide à la décision. Miroir de `SCORE_BANDS`
 * (backend `hiring_decision_service.py`).
 */
export const SCORE_BANDS = { excellent: 85, good: 60, average: 30 } as const;

export function scoreBandClass(score: number | null | undefined): 'excellent' | 'good' | 'average' | 'poor' {
  const s = score ?? 0;
  if (s >= SCORE_BANDS.excellent) return 'excellent';
  if (s >= SCORE_BANDS.good) return 'good';
  if (s >= SCORE_BANDS.average) return 'average';
  return 'poor';
}

/** Ordre du parcours — pour les listes, filtres et légendes. */
export const APPLICATION_STATUSES: string[] = Object.keys(APPLICATION_STATUS_META);

/** Fins de parcours : aucune transition n'en sort (miroir de `TERMINAL`). */
const TERMINAL_STATUSES = new Set(['HIRED', 'REJECTED', 'WITHDRAWN']);
/** Les deux seuls retours en arrière admis par le backend. */
const RETOURS_ADMIS = new Set(['ACCEPTED>NEGOTIATION', 'NEGOTIATION>INTERVIEW_SCHEDULED', 'ON_HOLD>INTERVIEW_SCHEDULED']);
const PARCOURS = APPLICATION_STATUSES.filter((s) => s !== 'REJECTED' && s !== 'WITHDRAWN');

export function isTerminalStatus(statut: string | null | undefined): boolean {
  return !!statut && TERMINAL_STATUSES.has(statut);
}

/**
 * Miroir de `can_transition` (`app/models/application_status.py`) : avancer
 * est libre, reculer ne l'est que dans deux cas, une fin de parcours est figée.
 */
export function canTransitionStatus(current: string | null | undefined, target: string): boolean {
  if (!APPLICATION_STATUS_META[target]) return false;
  if (!current || !APPLICATION_STATUS_META[current]) return true;
  if (TERMINAL_STATUSES.has(current)) return false;
  if (target === 'REJECTED' || target === 'WITHDRAWN') return true;
  const depart = PARCOURS.indexOf(current);
  const arrivee = PARCOURS.indexOf(target);
  if (arrivee > depart) return true;
  if (arrivee === depart) return target === 'INTERVIEW_SCHEDULED';
  return RETOURS_ADMIS.has(`${current}>${target}`);
}

/**
 * Options d'un sélecteur de statut : le statut actuel en tête (toujours
 * présent, même inconnu, pour que le champ ne s'affiche jamais vide), puis
 * les seules cibles que le serveur acceptera.
 */
export function statusOptionsFor(current: string | null | undefined): string[] {
  const cibles = APPLICATION_STATUSES.filter((s) => s !== current && canTransitionStatus(current, s));
  return current ? [current, ...cibles] : cibles;
}

/** Libellé français, ou la clé brute si elle est inconnue — jamais vide. */
export function applicationStatusLabel(statut: string | null | undefined): string {
  if (!statut) return '—';
  return APPLICATION_STATUS_META[statut]?.label ?? statut;
}

export function applicationStatusColor(statut: string | null | undefined): string {
  return (statut && APPLICATION_STATUS_META[statut]?.color) || '#A4B0B0';
}

export interface JobOffer {
  id: string;
  title: string;
  description: string;
  salary_min: number | null;
  salary_max: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  required_skills?: string[];
  required_experience_years?: number;
  required_education_level?: string;
  weight_skills?: number;
  weight_experience?: number;
  weight_education?: number;
  work_mode?: WorkMode | null;
  contract_types?: ContractType[] | null;
  status?: JobStatus;
  expires_at?: string | null;
}

export interface Application {
  id: string;
  candidate_id: string;
  candidate_name?: string;
  job_offer_id: string;
  job_offer_title?: string;
  cv_file_path: string;
  status: string;
  /** Prétention annoncée par le candidat pour cette offre (TND/mois). */
  expected_salary?: number | null;
  created_at: string;
  updated_at: string;
}

/**
 * État du CV de référence. Le chemin du fichier n'est jamais exposé par
 * l'API — seuls le nom d'origine et la date de dépôt remontent.
 */
export interface CandidateCv {
  has_cv: boolean;
  filename?: string | null;
  uploaded_at?: string | null;
}

export interface MyApplication {
  id: string;
  job_offer_id: string;
  candidate_id: string;
  cv_file_path: string;
  status: string;
  created_at: string;
  updated_at: string;
  job_title: string;
  job_description: string;
  job_salary_min: number | null;
  job_salary_max: number | null;
  job_required_skills: string[] | null;
  job_required_experience_years: number | null;
  job_required_education_level: string | null;
  job_is_active: boolean;
  job_work_mode?: WorkMode | null;
  job_contract_types?: ContractType[] | null;
  total_score: number | null;
  skills_score: number | null;
  experience_score: number | null;
  education_score: number | null;
  expected_salary?: number | null;
}

/**
 * Une offre recommandée d'après le CV analysé du candidat.
 *
 * `compatibility_score` (0..1) combine les critères métier — compétences,
 * expérience, formation, pondérés par l'offre — et la proximité sémantique
 * CV ↔ offre. C'est une adéquation de profil, pas une chance d'être retenu :
 * `reasons` existe pour que le chiffre puisse se lire au lieu d'être subi.
 */
export interface JobRecommendation {
  job_id: string;
  title: string;
  compatibility_score: number;
  matching_skills: string[];
  missing_skills: string[];
  reasons: string[];
  salary_min?: number | null;
  salary_max?: number | null;
  work_mode?: WorkMode | null;
  contract_types?: ContractType[] | null;
}

export interface JobOfferWithCandidateCount extends JobOffer {
  candidate_count: number;
}

export interface JobExtractionFields {
  title?: string;
  description?: string;
  required_skills?: string[];
  required_experience_years?: number;
  required_education_level?: string;
  work_mode?: string;
  contract_types?: string[];
}

export interface JobExtractionResponse {
  ok: boolean;
  fields: JobExtractionFields;
  reason: string | null;
}

export interface SalarySuggestion {
  predicted_salary: number;
  range_min: number;
  range_max: number;
  confidence: number;
  model_type: string;
  currency?: string;
  period?: string;
}

export interface NegotiationChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface NegotiationChatResponse {
  reply: string;
  recommendation: 'accept' | 'counter' | 'reject' | null;
  suggested_amount: number | null;
  predicted_salary: number | null;
  source: 'llm' | 'heuristic';
}

/** Un fait de l'analyse, avec la tonalité d'affichage décidée côté backend. */
export interface NegotiationExplanationLine {
  /** Place à l'écran : l'action, une alerte, ou un fait déjà montré en chiffres. */
  kind: 'recommendation' | 'alert' | 'budget' | 'profile' | 'market';
  tone: 'success' | 'info' | 'warn' | 'danger';
  text: string;
}

/**
 * Signaux cumulables, indépendants du verdict :
 *  - `above_market` / `below_market` : la demande sort de la fourchette de marché
 *  - `budget_below_market` : c'est l'OFFRE qui est sous le marché (risque de rétention)
 *  - `top_of_range` : la demande vaut exactement le maximum annoncé
 *  - `overqualified` / `underqualified` : niveau du candidat vs poste
 */
export type NegotiationSignal =
  | 'above_market' | 'below_market' | 'budget_below_market'
  | 'top_of_range' | 'overqualified' | 'underqualified';

export interface NegotiationAnalysis {
  candidate_name: string;
  job_title: string;
  candidate_experience_years: number | null;
  experience_source: 'cv' | 'candidate_score' | 'job_requirement';
  required_experience_years: number | null;
  experience_gap_years: number | null;
  match_score: number | null;
  qualification_score: number;

  // Marché : une fourchette, jamais un point.
  market_min: number;
  market_max: number;
  market_reference: number;
  market_gap: number;
  job_seniority_label: string;
  confidence: number;

  // Budget de l'offre : la seule référence d'acceptation.
  budget_min: number;
  budget_max: number;
  budget_overrun: number;
  position_in_range: number | null;

  requested_salary: number;
  verdict: 'acceptable' | 'counter_offer' | 'stretch' | 'negotiation_required';
  /** Étiquette grossière, utile pour trier et filtrer. */
  decision: 'ACCEPT' | 'COUNTER' | 'NEGOTIATE' | 'HIGH_REQUEST';
  /** Score pondéré 30/30/20/20 — expérience, matching, marché, budget. */
  negotiation_score: number;
  score_breakdown: {
    experience: number;
    matching: number | null;
    market_position: number;
    budget: number;
    weights: Record<string, number>;
  };
  signals: NegotiationSignal[];
  is_qualified: boolean;
  is_exceptional: boolean;
  recommended_salary: number;
  explanation: string;
  explanation_lines: NegotiationExplanationLine[];

  // Rétro-compatibilité.
  predicted_salary: number;
  predicted_range: number[];
  base_salary: number;
}

export interface PaginatedJobs {
  total: number;
  page: number;
  size: number;
  items: JobOffer[];
}

export interface CandidateRanking {
  candidate_id: string;
  candidate_name?: string;
  application_id: string;
  total_score: number;
  rank: number | null;
  skills_score: number;
  experience_score: number;
  education_score: number;
  score_details: ScoreDetails | null;
  // Set when the backend finds an active interview invitation for this app.
  interview_status?: 'PENDING' | 'CONFIRMED' | null;
  interview_invitation_id?: string | null;
  interview_confirmed_at?: string | null;
  /** L'entretien confirmé a déjà eu lieu : il reste au dossier mais ne retient plus le bouton « Planifier ». */
  interview_ended?: boolean;
  /** Prétention annoncée au dépôt — pré-remplit la page Négociation. */
  expected_salary?: number | null;

  /** État de la dernière session de test technique, et sa note si corrigée. */
  test_status?: 'ENVOYE' | 'EN_COURS' | 'TERMINE' | 'EXPIRE' | 'ABANDONNE' | null;
  test_score?: number | null;
  /**
   * Éligibilité décidée par le SERVEUR — le seuil de score ne descend pas
   * jusqu'ici. `can_schedule_interview` à faux n'interdit pas l'entretien :
   * il signale qu'un test est en attente, et l'écran atténue le bouton.
   */
  can_send_test?: boolean;
  can_schedule_interview?: boolean;
}

export interface RankingResponse {
  job_offer_id: string;
  total_candidates: number;
  ranking: CandidateRanking[];
}

export interface ScoreDetails {
  matched_skills: string[];
  missing_skills: string[];
  required_skills: string[];
  extracted_years: number | null;
  required_years: number | null;
  extracted_education: string | null;
  required_education: string | null;
  weights: { skills: number; experience: number; education: number };
  strengths: string[];
  weaknesses: string[];
  recommendation: string;
}

export interface CandidateScoreResponse {
  id: string;
  application_id: string;
  job_offer_id: string;
  candidate_id: string;
  total_score: number;
  skills_score: number;
  experience_score: number;
  education_score: number;
  rank: number | null;
  score_details: ScoreDetails | null;
  computed_at: string;
}

export interface CVAnalysisResponse {
  id: string;
  application_id: string;
  candidate_id: string;
  extracted_skills: string[];
  extracted_experience_years: number | null;
  extracted_education_level: string;
  extracted_job_titles: string[];
  extracted_keywords: string[];
  is_parsed: boolean;
  parsed_at: string | null;
  created_at: string;
}

export interface AnalysisStartedResponse {
  message: string;
  application_id: string | null;
  job_id: string | null;
}

export interface LabelCount { label: string; count: number; }
export interface ApplicationsTimeline {
  series: { date: string; label: string; count: number }[];
  total: number;
}
export interface CandidateAnalytics {
  experience_buckets: LabelCount[];
  score_bands: LabelCount[];
  education: LabelCount[];
  top_skills: LabelCount[];
  analyzed_cvs: number;
  scored_candidates: number;
  generated_at: string;
}

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

// ─── Interview workflow ───
export type InvitationStatus = 'PENDING' | 'CONFIRMED' | 'EXPIRED' | 'CANCELLED';
export type SlotState = 'AVAILABLE' | 'PROPOSED' | 'RESERVED';

export interface InterviewSlot {
  id: string;
  invitation_id: string;
  start_at: string;
  end_at: string;
  is_selected: boolean;
}

/**
 * Étape de l'entretien, calculée par le serveur — c'est elle qui range la
 * carte dans un onglet (le statut de l'invitation ne dit que l'échange).
 */
export type InterviewStage = 'A_VENIR' | 'A_EVALUER' | 'EVALUE' | 'EN_ATTENTE' | 'ABSENT' | 'ANNULE';

/** Une personne qui mène l'entretien. Seuls les membres peuvent l'évaluer. */
export interface InterviewMember {
  id: string;
  name: string;
  email: string;
}

export interface InvitationResponse {
  id: string;
  application_id: string;
  token: string;
  status: InvitationStatus;
  message: string | null;
  expires_at: string;
  confirmed_slot_id: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  created_at: string;
  updated_at: string;
  slots: InterviewSlot[];
  candidate_name: string | null;
  candidate_email: string | null;
  job_title: string | null;
  public_url: string;
  /** Lien de visioconférence de l'entretien confirmé (Google Meet ou Jitsi). */
  meet_url: string | null;
  /** Recruteur désigné pour conduire l'entretien. */
  assigned_recruiter_id: string | null;
  assigned_recruiter_name: string | null;
  assigned_recruiter_email: string | null;
  members: InterviewMember[];
  stage: InterviewStage;
  /** L'utilisateur connecté est membre de l'entretien : il peut l'évaluer. */
  can_evaluate: boolean;
  evaluated_at: string | null;
  /** Note d'entretien de la candidature (0–100). */
  interview_score: number | null;
  job_offer_id: string | null;
  application_status: string | null;
}

export interface PublicInvitationView {
  status: InvitationStatus;
  expires_at: string;
  message: string | null;
  candidate_name: string;
  job_title: string;
  job_description: string | null;
  company_name: string;
  slots: InterviewSlot[];
  confirmed_slot: InterviewSlot | null;
  meet_url: string | null;
}

export interface CalendarSlot {
  id: string;
  invitation_id: string;
  application_id: string;
  start_at: string;
  end_at: string;
  state: SlotState;
  candidate_name: string | null;
  job_title: string | null;
  invitation_status: InvitationStatus;
  confirmed_at: string | null;
  meet_url: string | null;
}

export interface CalendarResponse {
  total: number;
  items: CalendarSlot[];
}

@Injectable({ providedIn: 'root' })
export class RecruitmentService {
  constructor(private api: ApiService) {}

  /** Listing public (frontoffice) : uniquement les offres publiées et non expirées. */
  getJobs(
    page = 1,
    size = 10,
    search?: string,
    sortBy?: string,
    filters?: { work_mode?: string; contract_type?: string },
  ): Observable<PaginatedJobs> {
    const params: Record<string, string | number> = { page, size };
    if (search) params['search'] = search;
    if (sortBy) params['sort_by'] = sortBy;
    if (filters?.work_mode) params['work_mode'] = filters.work_mode;
    if (filters?.contract_type) params['contract_type'] = filters.contract_type;
    return this.api.get<PaginatedJobs>('recruitment/jobs', params);
  }

  /** Listing backoffice : inclut les brouillons, les offres fermées et expirées. */
  getJobsForManagement(
    page = 1,
    size = 10,
    search?: string,
    sortBy?: string,
    filters?: { status?: string; work_mode?: string; contract_type?: string },
  ): Observable<PaginatedJobs> {
    const params: Record<string, string | number> = { page, size };
    if (search) params['search'] = search;
    if (sortBy) params['sort_by'] = sortBy;
    if (filters?.status) params['status'] = filters.status;
    if (filters?.work_mode) params['work_mode'] = filters.work_mode;
    if (filters?.contract_type) params['contract_type'] = filters.contract_type;
    return this.api.get<PaginatedJobs>('recruitment/jobs/manage', params);
  }

  getJob(jobId: string): Observable<JobOffer> {
    return this.api.get<JobOffer>(`recruitment/jobs/${jobId}`);
  }

  /** Offres similaires (compétences, expérience, mode de travail) pour le bas de la page de détail. */
  getSimilarJobs(jobId: string, limit = 4): Observable<JobOffer[]> {
    return this.api.get<JobOffer[]>(`recruitment/jobs/${jobId}/similar`, { limit });
  }

  /**
   * Offres recommandées au candidat connecté, d'après son CV analysé.
   *
   * Une liste vide est le cas nominal (CV pas encore analysé, aucune offre
   * au-dessus du seuil de compatibilité) : l'écran masque alors la section
   * plutôt que d'afficher des cartes vides.
   */
  getMyRecommendedJobs(limit = 6): Observable<JobRecommendation[]> {
    return this.api
      .get<{ recommendations: JobRecommendation[] }>(
        'recruitment/me/recommended-jobs', { limit })
      .pipe(map(res => res?.recommendations ?? []));
  }

  createJob(data: any): Observable<JobOffer> {
    return this.api.post<JobOffer>('recruitment/jobs', data);
  }

  updateJob(jobId: string, data: any): Observable<JobOffer> {
    return this.api.patch<JobOffer>(`recruitment/jobs/${jobId}`, data);
  }

  deleteJob(jobId: string): Observable<void> {
    return this.api.delete<void>(`recruitment/jobs/${jobId}`);
  }

  /**
   * Dépose une candidature.
   *
   * `cvFile` est FACULTATIF : sans lui, le backend reprend le CV enregistré
   * dans le profil. `saveToProfile` fait du fichier joint le nouveau CV de
   * référence — c'est le cas courant, un candidat qui met son CV à jour en
   * postulant n'a pas à le redéposer ensuite.
   */
  applyToJob(jobId: string, cvFile?: File | null, saveToProfile = true): Observable<Application> {
    const formData = new FormData();
    if (cvFile) formData.append('cv_file', cvFile);
    formData.append('save_to_profile', String(saveToProfile));
    return this.api.postFormData<Application>(`recruitment/apply/${jobId}`, formData);
  }

  /** Prétention salariale du candidat ; `null` efface le montant. */
  setExpectedSalary(applicationId: string, amount: number | null): Observable<Application> {
    return this.api.patch<Application>(
      `recruitment/applications/${applicationId}/expected-salary`,
      { expected_salary: amount },
    );
  }

  // ── CV de référence du candidat ────────────────────────────────────────────

  getMyCv(): Observable<CandidateCv> {
    return this.api.get<CandidateCv>('recruitment/me/cv');
  }

  uploadMyCv(cvFile: File): Observable<CandidateCv> {
    const formData = new FormData();
    formData.append('cv_file', cvFile);
    return this.api.postFormData<CandidateCv>('recruitment/me/cv', formData);
  }

  deleteMyCv(): Observable<CandidateCv> {
    return this.api.delete<CandidateCv>('recruitment/me/cv');
  }

  /**
   * Vérifie qu'un document est un CV, sans l'enregistrer ni exiger de compte :
   * sert au formulaire d'inscription. Un refus arrive en 400, avec le message
   * à montrer au candidat dans `error.detail`.
   */
  verifierCv(cvFile: File): Observable<{ decision: string }> {
    const formData = new FormData();
    formData.append('cv_file', cvFile);
    return this.api.postFormData<{ decision: string }>('recruitment/cv/verification', formData);
  }

  getApplications(jobId?: string, page = 1, size = 20): Observable<Application[]> {
    const params: Record<string, string | number> = { page, size };
    if (jobId) params['job_id'] = jobId;
    return this.api.get<Application[]>('recruitment/applications', params);
  }

  /** Authenticated user's own applications, enriched with job offer details + score. */
  getMyApplications(): Observable<MyApplication[]> {
    return this.api.get<MyApplication[]>('recruitment/my-applications');
  }

  getApplicationsByJob(jobId: string): Observable<Application[]> {
    return this.api.get<Application[]>(`recruitment/jobs/${jobId}/applications`);
  }

  updateApplication(appId: string, status: string): Observable<Application> {
    return this.api.patch<Application>(`recruitment/applications/${appId}`, { status });
  }

  /** CAND-08 — hard-delete an application (Admin only). */
  deleteApplication(appId: string): Observable<void> {
    return this.api.delete<void>(`recruitment/applications/${appId}`);
  }

  /** Full update of a job offer (PUT). */
  replaceJob(jobId: string, data: any): Observable<JobOffer> {
    return this.api.put<JobOffer>(`recruitment/jobs/${jobId}`, data);
  }

  // ─── Saved jobs (frontoffice bookmarks) ───
  getSavedJobs(): Observable<JobOffer[]> {
    return this.api.get<JobOffer[]>('recruitment/saved-jobs');
  }

  saveJob(jobId: string): Observable<JobOffer> {
    return this.api.post<JobOffer>(`recruitment/saved-jobs/${jobId}`, {});
  }

  unsaveJob(jobId: string): Observable<void> {
    return this.api.delete<void>(`recruitment/saved-jobs/${jobId}`);
  }

  /** Export applications as a CSV blob (optionally filtered by job). */
  exportApplications(jobId?: string): Observable<Blob> {
    const qs = jobId ? `?job_id=${jobId}` : '';
    return this.api.http.get(
      `${environment.apiUrl}/recruitment/applications/export${qs}`,
      { responseType: 'blob' },
    );
  }

  getCVDownloadUrl(cvPath: string): string {
    const encodedPath = encodeURIComponent(cvPath);
    return `http://localhost:8000/api/v1/recruitment/cv-download/${encodedPath}`;
  }

  getCVPreviewUrl(cvPath: string): string {
    const encodedPath = encodeURIComponent(cvPath);
    return `http://localhost:8000/api/v1/recruitment/cv-preview/${encodedPath}`;
  }

  downloadCVAsBlob(cvPath: string): Observable<Blob> {
    const encodedPath = encodeURIComponent(cvPath);
    return this.api.http.get(`http://localhost:8000/api/v1/recruitment/cv-preview/${encodedPath}`,
      { responseType: 'blob' });
  }

  analyzeApplication(appId: string): Observable<AnalysisStartedResponse> {
    return this.api.post<AnalysisStartedResponse>(`recruitment/applications/${appId}/analyze`, {});
  }

  /** Trigger CV analysis + scoring for all applications of a job. */
  analyzeAllForJob(jobId: string): Observable<AnalysisStartedResponse> {
    return this.api.post<AnalysisStartedResponse>(`recruitment/jobs/${jobId}/analyze-all`, {});
  }

  /** Live recruitment KPIs (reports module). */
  getRecruitmentSummary(): Observable<RecruitmentSummary> {
    return this.api.get<RecruitmentSummary>('reports/recruitment-summary');
  }

  /** Candidate distributions (experience, AI score band, education, top skills). */
  getCandidateAnalytics(): Observable<CandidateAnalytics> {
    return this.api.get<CandidateAnalytics>('reports/candidate-analytics');
  }

  /** Daily applications over the last N days (evolution chart). */
  getApplicationsTimeline(days = 14): Observable<ApplicationsTimeline> {
    return this.api.get<ApplicationsTimeline>('reports/applications-timeline', { days });
  }

  scheduleInterview(
    appId: string,
    slots: string[],
    message: string,
    durationMinutes = 30,
    expiresInHours = 48,
    memberIds: string[] = [],
    meetUrl?: string | null,
  ): Observable<{ message: string }> {
    return this.api.post(`recruitment/applications/${appId}/schedule-interview`, {
      slots,
      message,
      duration_minutes: durationMinutes,
      expires_in_hours: expiresInHours,
      ...(memberIds.length ? { recruiter_ids: memberIds } : {}),
      ...(meetUrl ? { meet_url: meetUrl } : {}),
    });
  }

  /**
   * Produit un lien de visioconférence avant que l'invitation n'existe.
   * `provider` dit ce qui a réellement été créé — à afficher tel quel plutôt
   * que d'annoncer « Google Meet ».
   */
  generateMeetLink(): Observable<{
    meet_url: string;
    provider: string;
    /** Vrai si le compte Google de l'appelant est lié à l'API Meet. */
    google_meet_linked: boolean;
    /** Présent si Google a refusé : API non activée, portée manquante, autorisation révoquée. */
    google_meet_error?: string;
    /** Faux si aucun client OAuth n'est déclaré côté serveur. */
    google_meet_configured?: boolean;
  }> {
    return this.api.post('interview/meet-link', {});
  }

  /** URL de consentement Google à ouvrir pour lier un compte Meet. */
  getGoogleMeetAuthorizeUrl(): Observable<{ authorize_url: string }> {
    return this.api.get('interview/google-meet/authorize');
  }

  /**
   * Crée (ou refait) le lien visio d'un entretien confirmé, et l'envoie au
   * candidat et au recruteur assigné.
   */
  createInvitationMeetLink(
    invitationId: string,
    regenerate = false,
  ): Observable<{
    meet_url: string;
    provider: string;
    sent: boolean;
    recipients?: number;
    google_meet_error?: string;
  }> {
    const q = regenerate ? '?regenerate=true' : '';
    return this.api.post(`interview/invitations/${invitationId}/meet-link${q}`, {});
  }

  // ─── Public (no auth) — invitation confirm page ───
  getPublicInvitation(token: string): Observable<PublicInvitationView> {
    return this.api.get<PublicInvitationView>(`interview/confirm/${token}`);
  }

  confirmInvitationSlot(token: string, slotId: string): Observable<PublicInvitationView> {
    return this.api.post<PublicInvitationView>(`interview/confirm/${token}`, { slot_id: slotId });
  }

  /** Lightweight check: does this application already have a PENDING/CONFIRMED invitation? */
  getActiveInvitationForApplication(appId: string): Observable<{
    active: boolean;
    id?: string;
    status?: InvitationStatus;
    token?: string;
    expires_at?: string;
    confirmed_slot_id?: string | null;
    confirmed_at?: string | null;
    public_url?: string;
  }> {
    return this.api.get(`interview/applications/${appId}/active-invitation`);
  }

  // ─── RH ───
  listInvitations(filter?: { status?: InvitationStatus; applicationId?: string }): Observable<InvitationResponse[]> {
    const params: Record<string, string | number> = {};
    if (filter?.status)        params['status']         = filter.status;
    if (filter?.applicationId) params['application_id'] = filter.applicationId;
    return this.api.get<InvitationResponse[]>('interview/invitations', params);
  }

  getInvitation(invitationId: string): Observable<InvitationResponse> {
    return this.api.get<InvitationResponse>(`interview/invitations/${invitationId}`);
  }

  cancelInvitation(invitationId: string, reason: string = ''): Observable<InvitationResponse> {
    return this.api.post<InvitationResponse>(`interview/invitations/${invitationId}/cancel`, { reason });
  }

  getInterviewCalendar(filter?: { dateFrom?: string; dateTo?: string; state?: SlotState }): Observable<CalendarResponse> {
    const params: Record<string, string> = {};
    if (filter?.dateFrom) params['date_from'] = filter.dateFrom;
    if (filter?.dateTo)   params['date_to']   = filter.dateTo;
    if (filter?.state)    params['state']     = filter.state;
    return this.api.get<CalendarResponse>('interview/calendar', params);
  }

  /** État de l'intégration Google Calendar côté serveur. */
  getGoogleCalendarStatus(): Observable<{ configured: boolean; calendar_id: string | null; reason: string | null }> {
    return this.api.get('interview/google-status');
  }

  /** (Re)pousse un entretien confirmé vers Google Calendar. */
  syncInvitationToGoogle(invitationId: string): Observable<{ synced: boolean; google_event_id: string; already: boolean }> {
    return this.api.post(`interview/invitations/${invitationId}/sync-google`, {});
  }

  /** Télécharge le fichier .ics (RFC 5545) d'un entretien confirmé. */
  downloadInvitationIcs(invitationId: string): Observable<Blob> {
    return this.api.http.get(`${environment.apiUrl}/interview/invitations/${invitationId}/ics`, {
      responseType: 'blob',
    });
  }

  rejectApplication(appId: string, message: string = ''): Observable<{ message: string }> {
    return this.api.post(`recruitment/applications/${appId}/reject`, { message });
  }

  startNegotiation(appId: string, employerOffer: number): Observable<any> {
    return this.api.post(`recruitment/applications/${appId}/start-negotiation`, { employer_offer: employerOffer });
  }

  /** Suggestion salariale basée sur le POSTE seul — utilisée à la création/édition d'une offre, avant tout candidat. */
  predictSalary(job: {
    title: string;
    description?: string;
    skills_text?: string;
    experience_years?: number | null;
  }): Observable<SalarySuggestion> {
    return this.api.post<SalarySuggestion>('negotiations/predict-salary', {
      title: job.title,
      description: job.description || '',
      skills_text: job.skills_text || '',
      experience_years: job.experience_years ?? null,
    });
  }

  /**
   * Pré-remplit le formulaire de création d'offre à partir d'un texte libre.
   *
   * Une PROPOSITION, jamais une création : aucune offre n'est enregistrée par
   * cet appel. Un champ absent de `fields` signifie que le texte source ne le
   * mentionnait pas — à distinguer d'une valeur vide saisie par le RH.
   */
  extractJobFromText(text: string): Observable<JobExtractionResponse> {
    return this.api.post<JobExtractionResponse>('recruitment/jobs/extract-from-text', { text });
  }

  negotiationChat(appId: string, message: string, history: NegotiationChatMessage[]): Observable<NegotiationChatResponse> {
    return this.api.post<NegotiationChatResponse>(`recruitment/applications/${appId}/negotiation-chat`, { message, history });
  }

  /** Analyse poste × candidat : la demande salariale du candidat est-elle justifiée par son profil réel ? */
  /**
   * `baseSalary` / `baseSalaryMax` décrivent la FOURCHETTE budgétaire du poste.
   * Le maximum est le seuil de dépassement budgétaire : sans lui, le backend
   * retombe sur le `salary_max` de l'offre.
   */
  negotiationAnalysis(
    appId: string,
    requestedSalary: number,
    baseSalary: number | null,
    baseSalaryMax: number | null = null,
  ): Observable<NegotiationAnalysis> {
    return this.api.post<NegotiationAnalysis>(`recruitment/applications/${appId}/negotiation-analysis`, {
      requested_salary: requestedSalary,
      base_salary: baseSalary,
      base_salary_max: baseSalaryMax,
    });
  }

  getRankedCandidates(jobId: string): Observable<RankingResponse> {
    return this.api.get<RankingResponse>(`recruitment/jobs/${jobId}/ranking`);
  }

  getScoreBreakdown(appId: string): Observable<CandidateScoreResponse> {
    return this.api.get<CandidateScoreResponse>(`recruitment/applications/${appId}/score`);
  }

  getExtractedCVData(appId: string): Observable<CVAnalysisResponse> {
    return this.api.get<CVAnalysisResponse>(`recruitment/applications/${appId}/analysis`);
  }
}
