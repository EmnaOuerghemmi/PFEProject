import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
}

export interface VerifyEmailRequest {
  email: string;
  code: string;
}

@Injectable({
  providedIn: 'root'
})
export class PasswordService {
  constructor(private api: ApiService) {}

  forgotPassword(email: string): Observable<any> {
    return this.api.post('auth/forgot-password', { email });
  }

  resetPassword(token: string, newPassword: string): Observable<any> {
    return this.api.post('auth/reset-password', { token, new_password: newPassword });
  }

  /**
   * Valide le code à usage unique reçu par e-mail.
   *
   * Répond par un couple de jetons : l'utilisateur vient de prouver qu'il
   * contrôle l'adresse, la session s'ouvre donc directement — il n'a pas à
   * ressaisir le mot de passe qu'il vient de choisir.
   */
  verifyEmail(email: string, code: string): Observable<{ access_token: string; refresh_token: string }> {
    return this.api.post<{ access_token: string; refresh_token: string }>(
      'auth/verify-email', { email, code },
    );
  }

  /** Renvoie un nouveau code (l'ancien est alors invalidé). */
  resendVerificationCode(email: string): Observable<{ message: string }> {
    return this.api.post<{ message: string }>('auth/resend-verification', { email });
  }
}
