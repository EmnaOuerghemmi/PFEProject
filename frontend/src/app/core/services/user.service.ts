import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { User, UserCreate, UserUpdate, UserAdminUpdate, PaginatedUsers } from '../models/user.model';

export interface UserListParams {
  page?: number;
  size?: number;
  role?: string;
  ministry?: string;
  is_active?: boolean;
  search?: string;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  resource: string | null;
  resource_id: string | null;
  details: Record<string, any> | null;
  ip_address: string | null;
  created_at: string;
}

export interface PaginatedAuditLogs {
  total: number;
  page: number;
  size: number;
  items: AuditLog[];
}

/** Résumé d'un test technique — jamais le détail des réponses. */
export interface ProfileTestSession {
  status: string;
  score?: number | null;
  correct_count?: number | null;
  question_count: number;
  submitted_at?: string | null;
}

export interface ProfileApplication {
  id: string;
  job_offer_id: string;
  job_title: string;
  status: string;
  status_label: string;
  applied_at: string;
  expected_salary?: number | null;
  cv_score?: number | null;
  composite_score?: number | null;
  /** 1 à 3 volets. Deux composites de complétude différente ne se comparent pas. */
  composite_completeness?: number | null;
  interview_score?: number | null;
  /** Ce que le RH a écrit pendant/après l'entretien — jamais partagé au candidat. */
  interview_notes?: string | null;
  /** Repère : la note retenue reste `interview_score`, celle du RH. */
  interview_ai_summary?: string | null;
  test?: ProfileTestSession | null;
}

export interface UserProfile {
  account: {
    id: string; email: string; username: string;
    full_name?: string | null; phone_number?: string | null;
    avatar_url?: string | null; role: string;
    is_active: boolean; is_verified: boolean; is_superuser: boolean;
    totp_enabled: boolean;
    department?: string | null; job_title?: string | null;
    last_login_at?: string | null; created_at: string; updated_at?: string | null;
  };
  /** Faux pour un RH ou un administrateur : la fiche s'arrête au compte. */
  is_candidate: boolean;
  candidate?: {
    id: string; full_name: string; phone?: string | null;
    cv_filename?: string | null;
    /** Sert à construire le lien d'aperçu — réservé au RH/admin. */
    cv_path?: string | null;
    cv_uploaded_at?: string | null;
    created_at: string;
  } | null;
  applications: ProfileApplication[];
  stats: {
    applications: number; tests_taken: number;
    interviews: number; best_score?: number | null;
  };
}

@Injectable({
  providedIn: 'root'
})
export class UserService {
  constructor(private api: ApiService) {}

  getMe(): Observable<User> {
    return this.api.get<User>('users/me');
  }

  updateMe(data: UserUpdate): Observable<User> {
    return this.api.patch<User>('users/me', data);
  }

  uploadAvatar(file: File): Observable<User> {
    const form = new FormData();
    form.append('file', file);
    return this.api.postFormData<User>('users/me/avatar', form);
  }

  /** Self-service account deletion (profile Danger zone). */
  deleteMe(): Observable<void> {
    return this.api.delete<void>('users/me');
  }

  /** Change own password. */
  changePassword(currentPassword: string, newPassword: string): Observable<any> {
    return this.api.post('auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
  }

  listUsers(params: UserListParams = {}): Observable<PaginatedUsers> {
    const queryParams: Record<string, string | number | boolean> = {};
    if (params.page !== undefined) queryParams['page'] = params.page;
    if (params.size !== undefined) queryParams['size'] = params.size;
    if (params.role) queryParams['role'] = params.role;
    if (params.ministry) queryParams['ministry'] = params.ministry;
    if (params.is_active !== undefined) queryParams['is_active'] = params.is_active;
    if (params.search) queryParams['search'] = params.search;
    return this.api.get<PaginatedUsers>('users', queryParams);
  }

  createUser(data: UserCreate): Observable<User> {
    return this.api.post<User>('users', data);
  }

  /**
   * Fiche complète d'un utilisateur.
   *
   * Deux formes selon la personne : un candidat amène son dossier et ses
   * candidatures, un compte interne s'arrête à son compte. Aucun secret
   * d'authentification n'en sort — le schéma serveur les exclut.
   */
  getUserProfile(userId: string): Observable<UserProfile> {
    return this.api.get<UserProfile>(`users/${userId}/profile`);
  }

  getUser(userId: string): Observable<User> {
    return this.api.get<User>(`users/${userId}`);
  }

  updateUser(userId: string, data: UserAdminUpdate): Observable<User> {
    return this.api.patch<User>(`users/${userId}`, data);
  }

  deleteUser(userId: string): Observable<void> {
    return this.api.delete<void>(`users/${userId}`);
  }

  getAuditLogs(userId?: string, page = 1, size = 50): Observable<PaginatedAuditLogs> {
    const params: Record<string, string | number> = { page, size };
    if (userId) params['user_id'] = userId;
    return this.api.get<PaginatedAuditLogs>('users/audit-logs', params);
  }

  getMyAuditLogs(page = 1, size = 20): Observable<PaginatedAuditLogs> {
    return this.api.get<PaginatedAuditLogs>('users/me/audit-logs', { page, size });
  }
}
