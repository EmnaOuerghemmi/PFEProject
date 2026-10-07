import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  RecruitmentSummary, CandidateAnalytics, ApplicationsTimeline,
} from '../../../core/services/recruitment.service';

@Injectable({
  providedIn: 'root'
})
export class DashboardService {
  private apiUrl = `${environment.apiUrl}/dashboard`;

  constructor(private http: HttpClient) {}

  /**
   * Get dashboard statistics
   * Returns: total_jobs, total_applications, total_hires, and if superadmin: active_users, new_users
   */
  getDashboardStats(): Observable<any> {
    return this.http.get(`${this.apiUrl}/stats`);
  }

  /**
   * Get recent applications (last 4)
   */
  getRecentApplications(limit: number = 4): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/recent-applications?limit=${limit}`);
  }

  /**
   * Get open positions (last 3)
   */
  getOpenPositions(limit: number = 3): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/open-positions?limit=${limit}`);
  }

  // ── Données des cartes fixes ──
  // Servies par le tableau de bord lui-même, et refusées (403) quand aucune
  // carte qui en dépend n'est partagée avec le rôle connecté.

  getRecruitmentSummary(): Observable<RecruitmentSummary> {
    return this.http.get<RecruitmentSummary>(`${this.apiUrl}/recruitment-summary`);
  }

  getCandidateAnalytics(): Observable<CandidateAnalytics> {
    return this.http.get<CandidateAnalytics>(`${this.apiUrl}/candidate-analytics`);
  }

  getApplicationsTimeline(days = 14): Observable<ApplicationsTimeline> {
    return this.http.get<ApplicationsTimeline>(`${this.apiUrl}/applications-timeline?days=${days}`);
  }
}
