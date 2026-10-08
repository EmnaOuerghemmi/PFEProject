import { Injectable, OnDestroy } from '@angular/core';
import { Subject, Subscription } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';
import { environment } from '../../../environments/environment';

export interface AppNotification {
  id: string;
  type: string;
  title: string;
  message: string;
  link: string | null;
  is_read: boolean;
  created_at: string;
  actor_id: string | null;
}

export interface PaginatedNotifications {
  items: AppNotification[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
}

/**
 * Notifications in-app : REST (liste, unread-count, mark-read) + WebSocket
 * temps réel. Un seul service partagé par le frontoffice (candidat) et le
 * backoffice (RH/Admin) — chacun ne voit que ses propres notifications
 * (scopées côté serveur par `recipient_id`).
 */
/** Code de fermeture envoyé par le serveur quand il refuse le jeton. */
const CODE_JETON_REFUSE = 4401;
const DELAI_INITIAL_MS = 5_000;
const DELAI_MAX_MS = 60_000;

@Injectable({ providedIn: 'root' })
export class NotificationService implements OnDestroy {
  /** Émet chaque notification poussée en temps réel par le WebSocket. */
  readonly incoming$ = new Subject<AppNotification>();

  private ws: WebSocketSubject<any> | null = null;
  private wsSub: Subscription | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Délai avant la prochaine reconnexion : double à chaque échec, plafonné. */
  private delaiReconnexion = DELAI_INITIAL_MS;

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnDestroy(): void {
    this.disconnect();
  }

  // ── REST ──────────────────────────────────────────────────────────────────

  list(page = 1, pageSize = 20, unreadOnly = false): import('rxjs').Observable<PaginatedNotifications> {
    return this.api.get<PaginatedNotifications>('notifications', {
      page, page_size: pageSize, unread_only: unreadOnly,
    });
  }

  getUnreadCount(): import('rxjs').Observable<{ unread_count: number }> {
    return this.api.get<{ unread_count: number }>('notifications/unread-count');
  }

  markRead(id: string): import('rxjs').Observable<{ id: string; is_read: boolean }> {
    return this.api.patch(`notifications/${id}/read`, {});
  }

  markAllRead(): import('rxjs').Observable<{ marked_read: number }> {
    return this.api.post('notifications/read-all', {});
  }

  remove(id: string): import('rxjs').Observable<void> {
    return this.api.delete<void>(`notifications/${id}`);
  }

  // ── WebSocket temps réel ──────────────────────────────────────────────────

  /** À appeler une fois l'utilisateur authentifié (ex. après login / au boot si déjà connecté). */
  connect(): void {
    const token = this.auth.getToken();
    if (!token || this.ws) return;

    this.ws = webSocket({
      url: `${environment.wsUrl}/notifications/ws?token=${encodeURIComponent(token)}`,
      openObserver: {
        next: () => {
          this.delaiReconnexion = DELAI_INITIAL_MS;
          console.debug('[Notifications] WS connecté');
        },
      },
      closeObserver: {
        next: (evenement: CloseEvent) => {
          this.ws = null;
          // Jeton refusé : réessayer avec le même jeton ne mènerait nulle part.
          if (evenement?.code === CODE_JETON_REFUSE) {
            this.verifierSession();
            return;
          }
          // Coupure (serveur redémarré, réseau) : on réessaie, de moins en moins souvent.
          if (this.auth.isAuthenticated() && !this.reconnectTimer) {
            this.reconnectTimer = setTimeout(() => {
              this.reconnectTimer = null;
              this.connect();
            }, this.delaiReconnexion);
            this.delaiReconnexion = Math.min(this.delaiReconnexion * 2, DELAI_MAX_MS);
          }
        },
      },
    });

    this.wsSub = this.ws.subscribe({
      next: (msg: any) => {
        if (msg?.event === 'notification' && msg.data) {
          this.incoming$.next(msg.data as AppNotification);
        }
      },
      error: () => { this.ws = null; },
    });
  }

  /**
   * Le serveur a refusé le jeton. On laisse l'intercepteur trancher, comme pour
   * toute requête : il rafraîchit le jeton s'il a seulement expiré (et l'on se
   * reconnecte), ou constate une session morte — compte supprimé — et ramène
   * à la connexion.
   */
  private verifierSession(): void {
    this.api.get('users/me').subscribe({
      next: () => this.connect(),
      error: (err) => {
        if (err?.status === 401) this.auth.logout();
      },
    });
  }

  disconnect(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    this.wsSub?.unsubscribe();
    this.wsSub = null;
    this.ws?.complete();
    this.ws = null;
  }
}
