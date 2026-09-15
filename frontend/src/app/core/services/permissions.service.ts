import { Injectable, inject } from '@angular/core';
import { Observable, BehaviorSubject, of, tap, map, catchError } from 'rxjs';
import { ApiService } from './api.service';

export interface PermissionsResponse {
  role: string;
  /** Ressource → actions autorisées. `{"*": ["*"]}` signifie « tout ». */
  permissions: Record<string, string[]>;
}

/**
 * Ce que le rôle de l'utilisateur autorise, tel que le serveur le déclare.
 *
 * Sert UNIQUEMENT à l'affichage : masquer une entrée de menu plutôt que de
 * laisser ouvrir une page qui se remplira d'un 403. La décision fait toujours
 * autorité côté serveur — un utilisateur qui forcerait l'URL verrait la page
 * s'afficher, mais aucune donnée n'arriverait.
 *
 * La liste n'est demandée qu'une fois par session : elle ne change pas tant
 * que le rôle ne change pas, et le rôle ne change pas sans reconnexion.
 */
@Injectable({ providedIn: 'root' })
export class PermissionsService {
  private api = inject(ApiService);

  private readonly etat$ = new BehaviorSubject<Record<string, string[]> | null>(null);
  private enCours$: Observable<Record<string, string[]>> | null = null;

  /** Les permissions, chargées au besoin puis mises en cache. */
  charger(): Observable<Record<string, string[]>> {
    const cache = this.etat$.value;
    if (cache) return of(cache);
    if (this.enCours$) return this.enCours$;

    this.enCours$ = this.api.get<PermissionsResponse>('users/me/permissions').pipe(
      map(r => r.permissions ?? {}),
      // Un échec réseau ne doit pas bloquer la navigation sur un écran blanc :
      // on repart d'un jeu vide, le serveur refusera de toute façon ce qui
      // doit l'être.
      catchError(() => of({} as Record<string, string[]>)),
      tap(p => { this.etat$.next(p); this.enCours$ = null; }),
    );
    return this.enCours$;
  }

  /** Vrai si l'utilisateur peut agir ainsi. Lecture synchrone du cache. */
  peut(ressource: string, action: string): boolean {
    return this.evaluer(this.etat$.value, ressource, action);
  }

  private evaluer(
    perms: Record<string, string[]> | null, ressource: string, action: string,
  ): boolean {
    if (!perms) return false;
    if (perms['*']?.includes('*')) return true;   // administrateur
    return perms[ressource]?.includes(action) ?? false;
  }

  /** Version asynchrone, pour les gardes de route qui peuvent arriver avant le chargement. */
  peutAsync(ressource: string, action: string): Observable<boolean> {
    return this.charger().pipe(map(p => this.evaluer(p, ressource, action)));
  }

  /** À la déconnexion : le prochain utilisateur ne doit pas hériter du cache. */
  vider(): void {
    this.etat$.next(null);
    this.enCours$ = null;
  }
}
