import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface SemanticStatus {
  requested_backend: string;
  effective_backend: string;   // nom du modèle, ou 'hash-v1' (fallback)
  model_loaded: boolean;
  dim: number;
  pgvector: boolean;
  indexed_jobs: number;
  indexed_cvs: number;
}

export interface SemanticMatch {
  application_id: string;
  candidate_id: string;
  /** Compte utilisateur — adresse de la fiche back-office `/admin/users/:id`. */
  user_id: string | null;
  candidate_name: string;
  job_offer_id: string;
  job_title: string;
  application_status: string;
  semantic_score: number;        // 0..100
  keyword_score: number | null;  // score IA mots-clés existant (si calculé)
  skills: string[];
  experience_years: number | null;
}

export interface SemanticMatchResponse {
  job_offer_id: string;
  job_title: string;
  backend: string;
  pgvector: boolean;
  results: SemanticMatch[];
}

/** Matching sémantique CV↔offre (embeddings + pgvector) — backoffice RH/Admin. */
@Injectable({ providedIn: 'root' })
export class SemanticService {
  constructor(private api: ApiService) {}

  getStatus(): Observable<SemanticStatus> {
    return this.api.get<SemanticStatus>('semantic/status');
  }

  reindex(): Observable<{ jobs_indexed: number; cvs_indexed: number }> {
    return this.api.post('semantic/reindex', {});
  }

  matchCandidates(jobId: string, limit = 10): Observable<SemanticMatchResponse> {
    return this.api.get<SemanticMatchResponse>(`semantic/jobs/${jobId}/match`, { limit });
  }
}
