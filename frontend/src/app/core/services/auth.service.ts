import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import {
  Observable,
  BehaviorSubject,
  Subject,
  tap,
  catchError,
  EMPTY,
  throwError,
  switchMap,
  filter,
  take,
  finalize,
} from 'rxjs';
import { Router } from '@angular/router';
import { User } from '../models/user.model';
import { ApiService } from './api.service';
import { PermissionsService } from './permissions.service';

/** Réponse de `POST auth/2fa/setup`. */
export interface TotpSetup {
  /** Secret partagé, à saisir manuellement si le QR code est inutilisable. */
  secret: string;
  /** URI `otpauth://` à encoder en QR code pour l'application d'authentification. */
  provisioning_uri: string;
  /** Codes de secours en clair — affichés UNE SEULE FOIS, non récupérables ensuite. */
  backup_codes: string[];
}

/**
 * AuthService — session management.
 *
 * Persistence contract: once a user logs in, the access + refresh tokens are
 * stored in localStorage. Sessions are designed to PERSIST across page
 * reloads. We only clear the session when:
 *   - the user explicitly clicks "Logout"  (→ logout())
 *   - a refresh-token call definitively fails on the backend
 *     (→ jwt.interceptor catches the failure and clears)
 *
 * What we do NOT do anymore:
 *   - clear the session on initial /users/me failures
 *   - clear on network errors or non-401 errors
 *   - clear on backend-restart / transient 5xx
 *
 * The interceptor is the single point of truth for "session is dead" —
 * everything else is conservative.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private initializationSubject = new BehaviorSubject<boolean>(false);
  public isInitialized$ = this.initializationSubject.asObservable();

  // ── Concurrent-refresh coordination ──
  // The interceptor inspects `isRefreshing` and waits on `refreshDone$` so
  // many parallel 401s only trigger ONE call to /auth/refresh.
  private _isRefreshing = false;
  private refreshDone$ = new Subject<string | null>();

  private permissions = inject(PermissionsService);

  constructor(
    private http: HttpClient,
    private apiService: ApiService,
    private router: Router,
  ) {
    // Après la construction, pas pendant : la restauration lance une requête
    // HTTP, dont l'intercepteur demande à son tour AuthService. Encore en
    // construction, il déclenchait « NG0200 : dépendance circulaire », la
    // restauration échouait et, à chaque rechargement de page, l'utilisateur
    // connecté était renvoyé vers /login.
    queueMicrotask(() => this.initializeAuthState());
  }

  // ────────────────────────────────────────────────────────────────────
  //  Initialisation on app boot / page refresh
  // ────────────────────────────────────────────────────────────────────
  private initializeAuthState(): void {
    const accessToken = this.getToken();

    if (!accessToken) {
      // Not logged in — nothing to restore.
      this.initializationSubject.next(true);
      return;
    }

    console.debug('[AuthService] init: restoring session from localStorage');

    // We have tokens. Try to load the user. If /users/me returns 401, the
    // jwt.interceptor will transparently refresh the access token and retry.
    // We DO NOT clear localStorage here even on failure — the interceptor is
    // the only authority for "session is dead".
    this.loadCurrentUser().pipe(
      catchError(err => {
        console.warn(
          `[AuthService] init: /users/me failed (status=${err?.status}). ` +
          `Tokens kept; user can re-authenticate when needed.`,
        );
        return EMPTY;
      }),
    ).subscribe({
      next: user => {
        console.debug(`[AuthService] init: session restored for ${user?.email}`);
        this.initializationSubject.next(true);
      },
      error: () => this.initializationSubject.next(true),
      complete: () => this.initializationSubject.next(true),
    });
  }

  // ────────────────────────────────────────────────────────────────────
  //  HTTP calls
  // ────────────────────────────────────────────────────────────────────
  /**
   * `totpCode` n'est transmis que lorsqu'il est fourni : le backend renvoie
   * 401 « 2FA code required. » au premier appel si le compte est protégé,
   * l'écran de connexion demande alors le code et rejoue la requête.
   */
  login(email: string, password: string, totpCode?: string): Observable<any> {
    const body: Record<string, string> = { email, password };
    if (totpCode) {
      body['totp_code'] = totpCode;
    }
    return this.apiService.post('auth/login', body);
  }

  // ─── Double authentification (TOTP) ──────────────────────────────────────

  /**
   * Initialise la 2FA : génère un secret et des codes de secours côté serveur.
   * Le secret n'est PAS encore actif — il faut confirmer avec `enable2fa`.
   * Les codes de secours ne sont renvoyés qu'ici, en clair, une seule fois.
   *
   * `currentCode` n'est nécessaire que pour RÉINITIALISER une 2FA déjà active :
   * le serveur l'exige alors, pour qu'un vol de session ne permette pas de
   * remplacer le second facteur de la victime.
   */
  setup2fa(currentCode?: string): Observable<TotpSetup> {
    const body = currentCode ? { current_code: currentCode } : {};
    return this.apiService.post<TotpSetup>('auth/2fa/setup', body);
  }

  /** Confirme l'activation en prouvant que l'application d'authentification est bien configurée. */
  enable2fa(code: string): Observable<{ message: string }> {
    return this.apiService.post<{ message: string }>('auth/2fa/enable', { code });
  }

  /** Désactive la 2FA — exige un code valide, pour qu'un vol de session ne suffise pas. */
  disable2fa(code: string): Observable<{ message: string }> {
    return this.apiService.post<{ message: string }>('auth/2fa/disable', { code });
  }

  /**
   * Connexion par code de secours (usage unique), appareil TOTP indisponible.
   *
   * C'est une VARIANTE DE CONNEXION, pas une action authentifiée : elle
   * renvoie un couple de jetons comme `login`. L'ancienne signature ne prenait
   * que le code et s'appuyait sur un jeton d'accès existant — impossible à
   * satisfaire, puisqu'on y recourt justement quand on ne peut pas se connecter.
   */
  useBackupCode(email: string, password: string, code: string): Observable<any> {
    return this.apiService.post('auth/2fa/backup', { email, password, code });
  }

  /**
   * Inscription publique. `role` n'est volontairement pas exposé : le serveur
   * crée systématiquement le compte en lecture seule.
   */
  register(user: { email: string; username: string; password: string; full_name?: string }): Observable<any> {
    return this.apiService.post('auth/register', user);
  }

  loginWithGoogle(idToken: string): Observable<any> {
    return this.apiService.post('auth/google', { id_token: idToken });
  }

  logout(): void {
    console.debug('[AuthService] logout: clearing session');
    // Call logout endpoint (revokes refresh token server-side) but ALWAYS
    // clear the local session whether the request succeeds or not.
    this.apiService.post('auth/logout', {}).subscribe({
      next: () => this.finishLogout(),
      error: () => this.finishLogout(),
    });
  }

  private finishLogout(): void {
    this.clearSession();
    this.router.navigate(['/login']);
  }

  /**
   * Calls /auth/refresh, stores the rotated tokens, and emits the new
   * access token on `refreshDone$` so any queued interceptor calls can
   * retry their request. ONLY clears the session if the refresh call
   * itself definitively fails — that means the session is truly dead.
   */
  refreshTokens(): Observable<{ access_token: string; refresh_token: string }> {
    const refresh = this.getRefreshToken();
    if (!refresh) {
      console.warn('[AuthService] refresh: no refresh token in storage');
      this._isRefreshing = false;
      this.refreshDone$.next(null);
      return throwError(() => new Error('No refresh token'));
    }
    console.debug('[AuthService] refresh: calling /auth/refresh');
    this._isRefreshing = true;
    return this.apiService.post<{ access_token: string; refresh_token: string }>(
      'auth/refresh',
      { refresh_token: refresh },
    ).pipe(
      tap(res => {
        if (res?.access_token)  this.setToken(res.access_token);
        if (res?.refresh_token) this.setRefreshToken(res.refresh_token);
        this.refreshDone$.next(res?.access_token ?? null);
        console.debug('[AuthService] refresh: ✔ rotated tokens stored');
      }),
      catchError(err => {
        // Format constant : une valeur venue du serveur ne doit pas pouvoir forger le message.
        console.error('[AuthService] refresh: ✗ failed (status=%s)', err?.status);
        // Refresh definitively failed → session is dead.
        this.clearSession();
        this.refreshDone$.next(null);
        return throwError(() => err);
      }),
      finalize(() => { this._isRefreshing = false; }),
    );
  }

  loadCurrentUser(): Observable<User> {
    // No catchError here — callers (initializeAuthState, interceptor)
    // decide how to react to errors. The interceptor will transparently
    // refresh on 401 if a refresh token is available.
    return this.apiService.get<User>('users/me').pipe(
      tap(user => this.currentUserSubject.next(user)),
    );
  }

  // ────────────────────────────────────────────────────────────────────
  //  State helpers
  // ────────────────────────────────────────────────────────────────────
  get isRefreshing(): boolean { return this._isRefreshing; }

  /** Emits the new access token (or null on failure) once the in-flight
   *  refresh completes. Used by the interceptor to queue concurrent 401s. */
  onRefreshComplete(): Observable<string | null> {
    return this.refreshDone$.pipe(filter(v => v !== undefined), take(1));
  }

  getCurrentUser(): User | null {
    return this.currentUserSubject.getValue();
  }

  updateCurrentUser(user: User): void {
    this.currentUserSubject.next(user);
  }

  setToken(token: string): void {
    localStorage.setItem('access_token', token);
  }

  getToken(): string | null {
    return localStorage.getItem('access_token');
  }

  setRefreshToken(token: string): void {
    localStorage.setItem('refresh_token', token);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token');
  }

  isAuthenticated(): boolean {
    return !!this.getToken();
  }

  isAdminOrRH(): boolean {
    const user = this.getCurrentUser();
    return user ? (user.role === 'ADMIN' || user.role === 'RH') : false;
  }

  clearSession(): void {
    console.debug('[AuthService] clearSession() called');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    this.currentUserSubject.next(null);
    // Les permissions sont celles d'un RÔLE : les garder en mémoire ferait
    // hériter le compte suivant du menu du précédent, sur le même onglet.
    this.permissions.vider();
  }
}
