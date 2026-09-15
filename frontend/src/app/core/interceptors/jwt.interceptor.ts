import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, filter, switchMap, take, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

/**
 * JWT interceptor — keeps the user logged in across page reloads.
 *
 * Behaviour:
 *   1. Attaches `Authorization: Bearer <token>` to every authenticated request.
 *   2. On a 401 response, calls /auth/refresh once (queuing parallel 401s),
 *      stores the rotated tokens, and replays the original request.
 *   3. ONLY clears the session when the refresh call itself fails — that's
 *      the only signal that the session is definitively dead.
 *   4. Never clears on network errors, 5xx, CORS, or other transient issues.
 *
 * Endpoints we never touch (would cause infinite loops or shouldn't carry auth):
 *   - /auth/refresh   (the refresh call itself)
 *   - /auth/login, /auth/register, /auth/google
 *   - /auth/2fa/backup, /auth/forgot-password, /auth/reset-password,
 *     /auth/verify-email  (routes de connexion ou de récupération : elles
 *     s'utilisent précisément quand on n'a pas de session valide — y attacher
 *     un jeton périmé déclencherait une tentative de renouvellement inutile,
 *     et une redirection vers /login au milieu du parcours)
 *   - /interview/confirm/<token>  (public candidate page)
 */

const SKIP_URLS = [
  'auth/refresh',
  'auth/login',
  'auth/register',
  'auth/google',
  'auth/2fa/backup',
  'auth/forgot-password',
  'auth/reset-password',
  'auth/verify-email',
  'auth/resend-verification',
  '/interview/confirm/',
];

function shouldSkipAuth(url: string): boolean {
  return SKIP_URLS.some(s => url.includes(s));
}

function withAuth<T>(req: HttpRequest<T>, token: string | null): HttpRequest<T> {
  if (!token) return req;
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  // Auth-free endpoints just pass through unmodified.
  if (shouldSkipAuth(req.url)) {
    return next(req);
  }

  const token = authService.getToken();
  const authReq = withAuth(req, token);

  return next(authReq).pipe(
    catchError((err: HttpErrorResponse) => {
      // Anything other than 401 → don't touch the session.
      if (err.status !== 401) {
        return throwError(() => err);
      }
      // 401 but no refresh token → propagate (caller decides). DON'T wipe
      // localStorage here; the user may simply have no session yet.
      if (!authService.getRefreshToken()) {
        console.debug(`[jwtInterceptor] 401 on ${req.url} with no refresh token`);
        return throwError(() => err);
      }

      // Either trigger a refresh, or join the in-flight one.
      if (authService.isRefreshing) {
        console.debug(`[jwtInterceptor] 401 on ${req.url} — queueing during refresh`);
        return queueWaitingForRefresh(authService, req, next);
      }
      console.debug(`[jwtInterceptor] 401 on ${req.url} — refreshing then retry`);
      return performRefreshAndRetry(authService, router, req, next);
    }),
  );
};

/**
 * Trigger /auth/refresh (rotates tokens) and retry the original request with
 * the fresh access token. If the refresh fails, the session is dead — we
 * clear localStorage and redirect to /login.
 */
function performRefreshAndRetry(
  authService: AuthService,
  router: Router,
  req: HttpRequest<any>,
  next: (r: HttpRequest<any>) => Observable<any>,
): Observable<any> {
  return authService.refreshTokens().pipe(
    switchMap(res => {
      const fresh = res?.access_token ?? authService.getToken();
      console.debug(`[jwtInterceptor] refresh OK — retrying ${req.url}`);
      return next(withAuth(req, fresh));
    }),
    catchError(err => {
      console.warn('[jwtInterceptor] refresh failed — redirecting to /login');
      // authService.refreshTokens() already cleared the session in its
      // own catchError. Just navigate.
      router.navigate(['/login']);
      return throwError(() => err);
    }),
  );
}

/**
 * Wait for the in-flight refresh to finish, then replay this request with
 * the new token.
 */
function queueWaitingForRefresh(
  authService: AuthService,
  req: HttpRequest<any>,
  next: (r: HttpRequest<any>) => Observable<any>,
): Observable<any> {
  return authService.onRefreshComplete().pipe(
    take(1),
    filter((tok): tok is string => !!tok),
    switchMap(tok => next(withAuth(req, tok))),
    catchError(err => throwError(() => err)),
  );
}
