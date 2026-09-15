import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router, NavigationEnd } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { AuthService } from '../../../core/services/auth.service';
import { NotificationService, AppNotification } from '../../../core/services/notification.service';
import { AssistantWidgetComponent } from '../../../shared/components/assistant-widget/assistant-widget.component';
import { PermissionsService } from '../../../core/services/permissions.service';

/**
 * Backoffice layout shell. Each sidebar entry is a real Angular route
 * (`/admin/dashboard`, `/admin/jobs`, …) so:
 *   - The URL reflects the current page (bookmarkable, shareable)
 *   - Browser back / forward / refresh work as expected
 *   - The page title in the top bar follows the URL
 *
 * The `activeTab` field is now derived from the current URL via router
 * events; we keep the same key set as before so the tab-label dictionary
 * and the [class.active] bindings in the template stay valid.
 */
@Component({
  selector: 'app-backoffice',
  standalone: true,
  imports: [CommonModule, RouterModule, AssistantWidgetComponent],
  templateUrl: './backoffice.component.html',
  styleUrls: ['./backoffice.component.css'],
})
export class BackofficeComponent implements OnInit, OnDestroy {
  activeTab: string = 'dashboard';
  sidebarOpen = false;
  sidebarCollapsed = false;
  userName = 'Admin User';
  userRole = 'Administrateur';
  userInitial = 'A';
  currentUser: any;

  // Topbar notification counts
  msgCount = 0;
  notifCount = 0;
  notifications: AppNotification[] = [];
  notificationsOpen = false;

  private routerSub?: Subscription;
  private userSub?: Subscription;
  private notifSub?: Subscription;

  readonly tabLabels: { [key: string]: { title: string; subtitle: string } } = {
    dashboard:   { title: 'Tableau de bord',   subtitle: 'Vue d\'ensemble de la plateforme' },
    assistant:   { title: 'Assistant IA',       subtitle: 'Assistant CAG extractif, sans LLM' },
    contracts:   { title: 'Contrats',           subtitle: 'Onboarding et signature électronique' },
    jobs:        { title: 'Offres d\'emploi',  subtitle: 'Création et suivi des postes ouverts' },
    applications:{ title: 'Candidatures',      subtitle: 'Centralisation des dossiers reçus' },
    users:       { title: 'Utilisateurs',      subtitle: 'Comptes, rôles et permissions' },
    recruitment: { title: 'Recrutement',       subtitle: 'Pipeline de recrutement intelligent' },
    interviews:  { title: 'Entretiens',        subtitle: 'Planification et calendrier des entretiens' },
    career:      { title: 'Carrière',          subtitle: 'Évolution et plans de développement' },
    negotiation: { title: 'Négociation',       subtitle: 'Discussions avec les talents' },
  };

  constructor(
    private authService: AuthService,
    private router: Router,
    private notificationService: NotificationService,
    private permissions: PermissionsService,
  ) {}

  /**
   * Une entrée de menu ne s'affiche que si la page est réellement ouvrable.
   *
   * Les quinze entrées étaient montrées à tout le back-office : un recruteur
   * voyait « Budget » ou « Utilisateurs », cliquait, et tombait sur un écran
   * que l'API refusait de remplir. Masquer coûte moins cher à comprendre
   * qu'expliquer un refus.
   */
  peut(ressource: string, action: string): boolean {
    return this.permissions.peut(ressource, action);
  }

  ngOnInit(): void {
    // Le menu se dessine à partir d'elles : on les demande d'emblée.
    this.permissions.charger().subscribe();

    // ── Track current user for the sidebar footer ──
    this.userSub = this.authService.currentUser$.subscribe(user => {
      if (user) {
        this.currentUser = user;
        this.userName = user.full_name || 'Admin User';
        this.userRole = this.getRoleLabel(user.role);
        this.userInitial = user.full_name?.charAt(0).toUpperCase() || 'A';
      }
    });

    // ── Sync activeTab from the URL ──
    this.activeTab = this.tabKeyFromUrl(this.router.url);
    this.routerSub = this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
    ).subscribe((e: NavigationEnd) => {
      this.activeTab = this.tabKeyFromUrl(e.urlAfterRedirects);
      if (this.isMobileViewport()) this.closeSidebar();
    });

    // ── Notifications temps réel (actions RH → Admin, etc.) ──
    this.loadNotifications();
    this.notificationService.connect();
    this.notifSub = this.notificationService.incoming$.subscribe((notif) => {
      this.notifications = [notif, ...this.notifications].slice(0, 8);
      this.notifCount++;
    });
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
    this.userSub?.unsubscribe();
    this.notifSub?.unsubscribe();
  }

  private loadNotifications(): void {
    this.notificationService.list(1, 8).subscribe({
      next: (res) => (this.notifications = res.items),
    });
    this.notificationService.getUnreadCount().subscribe({
      next: (res) => (this.notifCount = res.unread_count),
    });
  }

  toggleNotifications(event?: Event): void {
    event?.stopPropagation();
    this.notificationsOpen = !this.notificationsOpen;
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (!target.closest('.notif-dropdown-host')) this.notificationsOpen = false;
  }

  openNotification(notif: AppNotification): void {
    if (!notif.is_read) {
      this.notificationService.markRead(notif.id).subscribe({
        next: () => {
          notif.is_read = true;
          this.notifCount = Math.max(0, this.notifCount - 1);
        },
      });
    }
    this.notificationsOpen = false;
    if (notif.link) this.router.navigateByUrl(notif.link);
  }

  markAllNotificationsRead(event?: Event): void {
    event?.stopPropagation();
    this.notificationService.markAllRead().subscribe({
      next: () => {
        this.notifications.forEach((n) => (n.is_read = true));
        this.notifCount = 0;
      },
    });
  }

  notifTimeAgo(iso: string): string {
    const diffMs = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "à l'instant";
    if (mins < 60) return `Il y a ${mins} min`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `Il y a ${hours}h`;
    return `Il y a ${Math.floor(hours / 24)}j`;
  }

  /** Extract the child segment after `/admin/` (e.g. /admin/jobs → 'jobs'). */
  private tabKeyFromUrl(url: string): string {
    const match = url.match(/^\/admin\/([^/?#]+)/);
    return match ? match[1] : 'dashboard';
  }

  get currentTabLabel() {
    return this.tabLabels[this.activeTab] || this.tabLabels['dashboard'];
  }

  toggleSidebar(): void {
    if (this.isMobileViewport()) {
      this.sidebarOpen = !this.sidebarOpen;
      return;
    }
    this.sidebarCollapsed = !this.sidebarCollapsed;
  }

  closeSidebar(): void {
    this.sidebarOpen = false;
  }

  private isMobileViewport(): boolean {
    return typeof window !== 'undefined' && window.innerWidth <= 768;
  }

  getRoleLabel(role: string): string {
    const labels: { [key: string]: string } = {
      ADMIN: 'Administrateur',
      RH: 'RH',
      RECRUTEUR: 'Recruteur',
    };
    return labels[role] || role;
  }

  logout(): void {
    this.authService.logout();
    this.notificationService.disconnect();
  }
}
