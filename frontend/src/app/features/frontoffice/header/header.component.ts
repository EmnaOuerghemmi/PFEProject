import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { NotificationService, AppNotification } from '../../../core/services/notification.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.css']
})
export class HeaderComponent implements OnInit, OnDestroy {
  isAuthenticated = false;
  mobileMenuOpen = false;
  profileMenuOpen = false;
  notificationsOpen = false;
  isScrolled = false;
  isMobile = false;
  currentUser: any = null;
  private userSub!: Subscription;
  private notifSub?: Subscription;

  notifications: AppNotification[] = [];
  unreadCount = 0;

  constructor(
    private authService: AuthService,
    private router: Router,
    private notificationService: NotificationService,
  ) {}

  get hasNotifications(): boolean {
    return this.unreadCount > 0;
  }

  /** Personnel de recrutement : il a accès au back-office. */
  get estPersonnel(): boolean {
    return ['ADMIN', 'RH', 'RECRUTEUR'].includes(this.currentUser?.role);
  }

  get displayName(): string {
    return this.currentUser?.full_name || this.currentUser?.name || this.currentUser?.username || this.currentUser?.email || 'Compte';
  }

  ngOnInit() {
    this.isAuthenticated = this.authService.isAuthenticated();
    this.checkMobileView();
    this.userSub = this.authService.currentUser$.subscribe(user => {
      const wasAuthenticated = this.isAuthenticated;
      this.currentUser = user;
      this.isAuthenticated = this.authService.isAuthenticated();
      if (this.isAuthenticated && !wasAuthenticated) this.initNotifications();
      if (!this.isAuthenticated) this.notificationService.disconnect();
    });
    if (this.isAuthenticated) {
      this.initNotifications();
      if (!this.currentUser) {
        this.authService.loadCurrentUser().subscribe({
          error: () => undefined,
        });
      }
    }
  }

  ngOnDestroy() {
    this.userSub?.unsubscribe();
    this.notifSub?.unsubscribe();
  }

  private initNotifications(): void {
    this.loadNotifications();
    this.notificationService.connect();
    this.notifSub = this.notificationService.incoming$.subscribe((notif) => {
      this.notifications = [notif, ...this.notifications].slice(0, 8);
      this.unreadCount++;
    });
  }

  loadNotifications(): void {
    this.notificationService.list(1, 8).subscribe({
      next: (res) => (this.notifications = res.items),
    });
    this.notificationService.getUnreadCount().subscribe({
      next: (res) => (this.unreadCount = res.unread_count),
    });
  }

  openNotification(notif: AppNotification): void {
    if (!notif.is_read) {
      this.notificationService.markRead(notif.id).subscribe({
        next: () => {
          notif.is_read = true;
          this.unreadCount = Math.max(0, this.unreadCount - 1);
        },
      });
    }
    this.notificationsOpen = false;
    if (notif.link) this.router.navigateByUrl(notif.link);
  }

  markAllNotificationsRead(): void {
    // Mise à jour immédiate ; on recharge l'état réel si le serveur refuse.
    this.notifications.forEach((n) => (n.is_read = true));
    this.unreadCount = 0;
    this.notificationService.markAllRead().subscribe({
      error: () => this.loadNotifications(),
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

  @HostListener('window:resize')
  onResize() {
    this.checkMobileView();
  }

  @HostListener('window:scroll')
  onScroll() {
    // Header transparent sur le haut du hero, verre sombre dès qu'on défile.
    this.isScrolled = window.scrollY > 60;
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (!target.closest('.dropdown-host') && !target.closest('.profile-btn')) {
      this.profileMenuOpen = false;
      this.notificationsOpen = false;
    }
  }

  checkMobileView() {
    this.isMobile = window.innerWidth <= 768;
    if (!this.isMobile) this.mobileMenuOpen = false;
  }

  toggleMobileMenu() {
    this.mobileMenuOpen = !this.mobileMenuOpen;
    this.profileMenuOpen = false;
    this.notificationsOpen = false;
  }

  toggleProfileMenu() {
    this.profileMenuOpen = !this.profileMenuOpen;
    this.notificationsOpen = false;
  }

  toggleNotifications() {
    this.notificationsOpen = !this.notificationsOpen;
    this.profileMenuOpen = false;
    // Ouvrir le panneau vaut lecture : pastille retirée, notifications lues.
    if (this.notificationsOpen && this.unreadCount > 0) this.markAllNotificationsRead();
  }

  closeMenus() {
    this.profileMenuOpen = false;
    this.notificationsOpen = false;
    this.mobileMenuOpen = false;
  }

  goLogin() {
    this.router.navigate(['/login']);
  }

  goSavedJobs() {
    this.closeMenus();
    this.router.navigate(['/frontoffice/saved-jobs']);
  }

  logout() {
    this.authService.logout();
    this.notificationService.disconnect();
    this.isAuthenticated = false;
    this.closeMenus();
  }

  getUserInitials(): string {
    if (!this.currentUser) return 'U';
    const name = this.currentUser.full_name || this.currentUser.username || this.currentUser.email || 'U';
    return name.split(' ').map((n: string) => n[0]).join('').substring(0, 2).toUpperCase();
  }
}
