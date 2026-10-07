import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { environment } from '../../../environments/environment';

export type ContractStatus = 'DRAFT' | 'SENT' | 'SIGNED' | 'ACTIVE' | 'DECLINED' | 'EXPIRED';

export interface Contract {
  id: string;
  application_id: string;
  contract_type: string;
  position: string;
  department: string | null;
  salary: number;
  currency: string;
  start_date: string | null;
  trial_period_months: number;
  weekly_hours: number;
  end_date: string | null;
  notes: string | null;
  status: ContractStatus;
  sent_at: string | null;
  expires_at: string | null;
  signed_at: string | null;
  signer_name: string | null;
  certificate_id: string | null;
  employee_id: string | null;
  created_at: string;
  candidate_name: string | null;
  candidate_email: string | null;
  job_title: string | null;
  public_url: string | null;
  /** Civilité écrite au contrat — accorde « né / née ». */
  employee_civility: 'M.' | 'Mme' | null;
  employee_birth_date: string | null;
  employee_cin: string | null;
  employee_cin_issue_date: string | null;
  employee_address: string | null;
}

/**
 * Candidature ACCEPTÉE sans contrat : reçue par la page Contrats avec le
 * salaire proposé et sa provenance, à confirmer par le RH.
 */
export interface PendingContract {
  application_id: string;
  candidate_name: string;
  candidate_email: string | null;
  candidate_phone: string | null;
  job_title: string;
  suggested_salary: number | null;
  salary_source: 'negotiation' | 'expected_salary' | 'offer_max' | 'offer_min' | null;
  expected_salary: number | null;
  budget_min: number | null;
  budget_max: number | null;
  currency: string;
  accepted_at: string | null;
}

export interface ContractStats {
  draft: number; sent: number; signed: number; active: number;
  declined: number; expired: number; total: number;
}

export interface PublicContract {
  status: ContractStatus;
  contract_type: string;
  position: string;
  department: string | null;
  salary: number;
  currency: string;
  start_date: string | null;
  trial_period_months: number;
  weekly_hours: number;
  end_date: string | null;
  candidate_name: string;
  job_title: string;
  company_name: string;
  expires_at: string | null;
  signed_at: string | null;
  certificate_id: string | null;
}

@Injectable({ providedIn: 'root' })
export class ContractService {
  constructor(private api: ApiService) {}

  // ── RH / Admin ──────────────────────────────────────────────────────────────
  list(statusFilter?: string): Observable<Contract[]> {
    return this.api.get<Contract[]>('contracts', statusFilter ? { status_filter: statusFilter } : undefined);
  }
  /** Candidats acceptés qui attendent leur contrat. */
  pending(): Observable<PendingContract[]> {
    return this.api.get<PendingContract[]>('contracts/pending');
  }

  stats(): Observable<ContractStats> {
    return this.api.get<ContractStats>('contracts/stats');
  }
  get(id: string): Observable<Contract> {
    return this.api.get<Contract>(`contracts/${id}`);
  }
  createFromApplication(applicationId: string, payload: Partial<Contract>): Observable<Contract> {
    return this.api.post<Contract>(`contracts/from-application/${applicationId}`, payload);
  }
  update(id: string, payload: Partial<Contract>): Observable<Contract> {
    return this.api.patch<Contract>(`contracts/${id}`, payload);
  }
  send(id: string, expiresInDays = 14): Observable<Contract> {
    return this.api.post<Contract>(`contracts/${id}/send`, { expires_in_days: expiresInDays });
  }
  remove(id: string): Observable<void> {
    return this.api.delete<void>(`contracts/${id}`);
  }
  downloadPdf(id: string): Observable<Blob> {
    return this.api.http.get(`${environment.apiUrl}/contracts/${id}/pdf`, { responseType: 'blob' });
  }

  // ── Public (signature candidat, sans auth) ───────────────────────────────────
  getPublic(token: string): Observable<PublicContract> {
    return this.api.get<PublicContract>(`contracts/sign/${token}`);
  }
  /** Contrat complet en PDF, lu par le candidat avant de signer. */
  getPublicPdf(token: string): Observable<Blob> {
    return this.api.http.get(`${environment.apiUrl}/contracts/sign/${token}/pdf`, { responseType: 'blob' });
  }
  sign(token: string, payload: { signer_name: string; signature_image: string; consent: boolean }): Observable<PublicContract> {
    return this.api.post<PublicContract>(`contracts/sign/${token}`, payload);
  }
  decline(token: string, reason: string): Observable<PublicContract> {
    return this.api.post<PublicContract>(`contracts/decline/${token}`, { reason });
  }
}
