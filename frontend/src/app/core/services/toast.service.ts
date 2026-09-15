import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  /** Titre optionnel, affiché en gras au-dessus du message. */
  title?: string;
}

/**
 * Notifications éphémères, en remplacement des `alert()` natifs.
 *
 * Pourquoi ne pas garder `alert()` : il bloque le fil d'exécution du
 * navigateur, ne peut pas être stylé, affiche le nom de domaine, et empile
 * des boîtes modales impossibles à enchaîner proprement.
 *
 * Les erreurs restent affichées plus longtemps que les succès : un message
 * d'échec doit laisser le temps de le lire, alors qu'une confirmation de
 * succès est redondante avec le changement d'état visible à l'écran.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private counter = 0;
  private readonly _toasts = signal<Toast[]>([]);

  /** Liste courante, consommée par ToastContainerComponent. */
  readonly toasts = this._toasts.asReadonly();

  private readonly defaultDuration: Record<ToastKind, number> = {
    success: 3500,
    info: 4000,
    warning: 5000,
    error: 6500,
  };

  success(message: string, title?: string): void {
    this.push('success', message, title);
  }

  error(message: string, title?: string): void {
    this.push('error', message, title);
  }

  info(message: string, title?: string): void {
    this.push('info', message, title);
  }

  warning(message: string, title?: string): void {
    this.push('warning', message, title);
  }

  /**
   * Affiche l'erreur d'une réponse HTTP.
   *
   * Le backend renvoie ses messages dans `error.detail` (FastAPI). On retombe
   * sur un texte générique plutôt que d'exposer une trace technique, illisible
   * pour l'utilisateur.
   */
  fromHttpError(err: unknown, fallback = "Une erreur est survenue."): void {
    const body = (err as { error?: { detail?: unknown; message?: unknown } })?.error;
    const message =
      (typeof body?.detail === 'string' && body.detail) ||
      ToastService.formatValidationErrors(body?.detail) ||
      (typeof body?.message === 'string' && body.message) ||
      fallback;
    this.error(message);
  }

  /**
   * Met en forme les erreurs de validation renvoyées par FastAPI (HTTP 422).
   *
   * Celles-ci arrivent sous forme de TABLEAU d'objets
   * `{ loc: ['body', 'champ'], msg: '…' }`, et non de chaîne : la lecture
   * précédente ne testait que le cas chaîne, si bien que toute erreur de
   * validation de l'application se réduisait au message générique de repli —
   * impossible de savoir quel champ posait problème.
   *
   * On ne garde que le dernier segment de `loc` : les précédents ('body',
   * 'query') n'apprennent rien à l'utilisateur.
   */
  private static formatValidationErrors(detail: unknown): string | null {
    if (!Array.isArray(detail) || !detail.length) return null;
    const lignes = detail
      .map((e: { loc?: unknown[]; msg?: string }) => {
        const champ = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : null;
        if (!e?.msg) return null;
        return champ ? `${champ} : ${e.msg}` : e.msg;
      })
      .filter((l): l is string => !!l);
    return lignes.length ? lignes.join(' · ') : null;
  }

  dismiss(id: number): void {
    this._toasts.update((list) => list.filter((t) => t.id !== id));
  }

  private push(kind: ToastKind, message: string, title?: string): void {
    const id = ++this.counter;
    this._toasts.update((list) => [...list, { id, kind, message, title }]);
    setTimeout(() => this.dismiss(id), this.defaultDuration[kind]);
  }
}
