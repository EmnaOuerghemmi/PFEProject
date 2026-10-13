import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface CagSource {
  id: string;
  title: string;
  category: string;
  source: string | null;
  score: number;
}

export interface CagAnswer {
  answer: string;
  confidence: number;
  sources: CagSource[];
  from_cache: boolean;
}

/** Une ligne de résultat de l'assistant, avec la page où agir. */
export interface AssistantElement {
  libelle: string;
  detail: string;
  lien: string | null;
  parametres: Record<string, string>;
}

/** Ce que l'assistant renvoie pour comprendre la relance suivante. */
export interface AssistantContexte {
  outil: string | null;
  offre_id: string | null;
}

export interface AssistantReponse {
  reponse: string;
  elements: AssistantElement[];
  /** Questions de relance, cliquables : l'assistant les comprend toutes. */
  suggestions: string[];
  contexte: AssistantContexte;
  /** Seulement pour une réponse tirée de la base de connaissances. */
  sources: CagSource[];
  confiance: number | null;
}

export interface CagCvPassage { content: string; score: number; }

export interface CagCvAnswer {
  answer: string;
  confidence: number;
  passages: CagCvPassage[];
  candidate_name: string | null;
}

export interface CagStatus {
  backend: string;
  knowledge_entries: number;
  cached_cv_chunks: number;
  answer_cache_size: number;
  kb_cache_loaded: boolean;
  mode: string;
}

export interface KnowledgeEntry {
  id: string;
  title: string;
  content: string;
  category: string;
  source: string | null;
  indexed: boolean;
}

/**
 * Assistant CAG (Cache-Augmented Generation) — moteur extractif hors-ligne,
 * sans LLM. Les réponses sont EXTRAITES de la base de connaissances / des CV
 * (zéro hallucination), avec citation de la source.
 */
@Injectable({ providedIn: 'root' })
export class CagService {
  constructor(private api: ApiService) {}

  getStatus(): Observable<CagStatus> {
    return this.api.get<CagStatus>('cag/status');
  }

  ask(question: string): Observable<CagAnswer> {
    return this.api.post<CagAnswer>('cag/ask', { question });
  }

  /** Assistant connecté aux données : n'importe quel message, une réponse tirée de la base. */
  message(message: string, contexte: AssistantContexte | null): Observable<AssistantReponse> {
    return this.api.post<AssistantReponse>('assistant/message', { message, contexte });
  }

  askCv(applicationId: string, question: string): Observable<CagCvAnswer> {
    return this.api.post<CagCvAnswer>(`cag/cv/${applicationId}/ask`, { question });
  }

  listKnowledge(): Observable<KnowledgeEntry[]> {
    return this.api.get<KnowledgeEntry[]>('cag/knowledge');
  }

  addKnowledge(payload: { title: string; content: string; category: string; source?: string }): Observable<any> {
    return this.api.post('cag/knowledge', payload);
  }

  deleteKnowledge(id: string): Observable<void> {
    return this.api.delete<void>(`cag/knowledge/${id}`);
  }

  reindex(): Observable<{ reindexed: number }> {
    return this.api.post<{ reindexed: number }>('cag/reindex', {});
  }
}
