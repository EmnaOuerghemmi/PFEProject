import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { InterviewEvaluationComponent } from '../../../shared/components/interview-evaluation/interview-evaluation.component';
import {
  RecruitmentService,
  InvitationResponse,
  InvitationStatus,
  CalendarSlot,
} from '../../../core/services/recruitment.service';

type StatusTab = 'ALL' | InvitationStatus;

/**
 * Combien de temps le lien de visioconférence reste proposé après la fin de
 * l'entretien. Au-delà, la salle est vide : le bouton ne mènerait nulle part.
 */
const VISIO_DUREE_DE_VIE_MS = 24 * 60 * 60 * 1000;

@Component({
  selector: 'app-interview-manager',
  standalone: true,
  imports: [CommonModule, FormsModule, InterviewEvaluationComponent],
  templateUrl: './interview-manager.component.html',
  styleUrl: './interview-manager.component.css',
})
export class InterviewManagerComponent implements OnInit {
  // Data
  invitations: InvitationResponse[] = [];
  filtered: InvitationResponse[] = [];

  // Filters / UI state
  statusTab: StatusTab = 'ALL';
  searchQuery = '';

  isLoading = false;
  errorMsg = '';

  // Selection / modals
  detail: InvitationResponse | null = null;
  cancelReason = '';
  copiedToken: string | null = null;
  toastMsg = '';

  // KPIs (computed off `invitations`)
  total = 0;
  countPending = 0;
  countConfirmed = 0;
  countExpired = 0;
  countCancelled = 0;

  readonly statusTabs: { value: StatusTab; label: string; tone: string }[] = [
    { value: 'ALL',       label: 'Toutes',     tone: 'all' },
    { value: 'PENDING',   label: 'En attente', tone: 'warn' },
    { value: 'CONFIRMED', label: 'Confirmées', tone: 'success' },
    { value: 'EXPIRED',   label: 'Expirées',   tone: 'muted' },
    { value: 'CANCELLED', label: 'Annulées',   tone: 'danger' },
  ];

  // ── Calendar view ──
  view: 'list' | 'calendar' = 'list';
  weekStart!: Date;
  calSlots: CalendarSlot[] = [];
  calLoading = false;
  calError = '';

  /**
   * Évaluation d'entretien — ouverte depuis la carte, une fois le rendez-vous
   * passé. Avant l'heure, il n'y a rien à évaluer : le bouton n'existe pas.
   */
  evaluationApplicationId: string | null = null;
  evaluationCandidat = '';

  // ── Google Calendar / ICS ──
  googleConfigured = false;
  syncingId: string | null = null;
  downloadingIcsId: string | null = null;

  constructor(private recruitment: RecruitmentService) {}

  ngOnInit() {
    this.weekStart = this.mondayOf(new Date());
    this.load();
    this.recruitment.getGoogleCalendarStatus().subscribe({
      next: (s) => (this.googleConfigured = s.configured),
      error: () => (this.googleConfigured = false),
    });
  }

  // ════════════ Google Calendar / ICS ════════════

  downloadIcs(inv: InvitationResponse, event: Event) {
    event.stopPropagation();
    this.downloadingIcsId = inv.id;
    this.recruitment.downloadInvitationIcs(inv.id).subscribe({
      next: (blob) => {
        this.downloadingIcsId = null;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `entretien_${(inv.candidate_name || 'candidat').replace(/\s+/g, '_')}.ics`;
        a.click();
        URL.revokeObjectURL(url);
        this.showToast('Fichier .ics téléchargé — importable dans Google/Outlook/Apple Calendar.');
      },
      error: () => {
        this.downloadingIcsId = null;
        this.showToast('Téléchargement .ics impossible.');
      },
    });
  }

  syncGoogle(inv: InvitationResponse, event: Event) {
    event.stopPropagation();
    this.syncingId = inv.id;
    this.recruitment.syncInvitationToGoogle(inv.id).subscribe({
      next: (res) => {
        this.syncingId = null;
        this.showToast(res.already
          ? 'Déjà synchronisé avec Google Calendar.'
          : 'Entretien ajouté à Google Calendar ✓');
      },
      error: (err) => {
        this.syncingId = null;
        this.showToast(err?.error?.detail || 'Synchronisation Google impossible.');
      },
    });
  }

  // ════════════ Calendar ════════════
  setView(v: 'list' | 'calendar') {
    this.view = v;
    if (v === 'calendar') this.loadCalendar();
  }

  loadCalendar() {
    this.calLoading = true;
    this.calError = '';
    const from = this.weekStart.toISOString();
    const to = this.addDays(this.weekStart, 7).toISOString();
    this.recruitment.getInterviewCalendar({ dateFrom: from, dateTo: to }).subscribe({
      next: res => { this.calSlots = res.items; this.calLoading = false; },
      error: err => {
        this.calError = err?.error?.detail || 'Impossible de charger le calendrier.';
        this.calLoading = false;
      },
    });
  }

  prevWeek() { this.weekStart = this.addDays(this.weekStart, -7); this.loadCalendar(); }
  nextWeek() { this.weekStart = this.addDays(this.weekStart, 7); this.loadCalendar(); }
  thisWeek() { this.weekStart = this.mondayOf(new Date()); this.loadCalendar(); }

  private mondayOf(d: Date): Date {
    const x = new Date(d);
    const offset = (x.getDay() + 6) % 7; // 0 = Monday
    x.setDate(x.getDate() - offset);
    x.setHours(0, 0, 0, 0);
    return x;
  }
  private addDays(d: Date, n: number): Date {
    const x = new Date(d); x.setDate(x.getDate() + n); return x;
  }
  private sameDay(a: Date, b: Date): boolean {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }
  private monthShort(d: Date): string {
    return ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'][d.getMonth()];
  }

  get weekDays(): { date: Date; label: string; dayNum: number; isToday: boolean; slots: CalendarSlot[] }[] {
    const labels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
    const today = new Date();
    const out = [];
    for (let i = 0; i < 7; i++) {
      const date = this.addDays(this.weekStart, i);
      // Seuls les entretiens CONFIRMÉS (créneau réservé par le candidat)
      // apparaissent au calendrier : les créneaux simplement proposés ou
      // libres encombraient la vue sans rien apporter au planning réel.
      const slots = this.calSlots
        .filter(s => s.state === 'RESERVED' && this.sameDay(new Date(s.start_at), date))
        .sort((a, b) => +new Date(a.start_at) - +new Date(b.start_at));
      out.push({ date, label: labels[i], dayNum: date.getDate(), isToday: this.sameDay(date, today), slots });
    }
    return out;
  }

  get weekLabel(): string {
    const end = this.addDays(this.weekStart, 6);
    return `${this.weekStart.getDate()} ${this.monthShort(this.weekStart)} – ${end.getDate()} ${this.monthShort(end)} ${end.getFullYear()}`;
  }

  get calCount(): number { return this.calSlots.filter(s => s.state === 'RESERVED').length; }

  openInvitation(invitationId: string) {
    this.recruitment.getInvitation(invitationId).subscribe({
      next: fresh => { this.detail = fresh; this.cancelReason = ''; },
    });
  }

  load() {
    this.isLoading = true;
    this.errorMsg = '';
    this.recruitment.listInvitations().subscribe({
      next: list => {
        this.invitations = list;
        this.computeKpis();
        this.rebuild();
        this.isLoading = false;
      },
      error: err => {
        this.errorMsg = err?.error?.detail || 'Impossible de charger les invitations.';
        this.isLoading = false;
      },
    });
  }

  computeKpis() {
    this.total = this.invitations.length;
    this.countPending   = this.invitations.filter(i => i.status === 'PENDING').length;
    this.countConfirmed = this.invitations.filter(i => i.status === 'CONFIRMED').length;
    this.countExpired   = this.invitations.filter(i => i.status === 'EXPIRED').length;
    this.countCancelled = this.invitations.filter(i => i.status === 'CANCELLED').length;
  }

  rebuild() {
    const q = this.searchQuery.trim().toLowerCase();
    this.filtered = this.invitations.filter(inv => {
      if (this.statusTab !== 'ALL' && inv.status !== this.statusTab) return false;
      if (!q) return true;
      const hay = [inv.candidate_name, inv.candidate_email, inv.job_title]
        .filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }

  // ── Filter handlers ──
  selectTab(t: StatusTab) {
    this.statusTab = t;
    this.rebuild();
  }

  onSearchChange() { this.rebuild(); }

  countFor(t: StatusTab): number {
    if (t === 'ALL') return this.total;
    return this.invitations.filter(i => i.status === t).length;
  }

  // ── Detail / cancel ──
  openDetail(inv: InvitationResponse) {
    this.recruitment.getInvitation(inv.id).subscribe({
      next: fresh => { this.detail = fresh; this.cancelReason = ''; },
      error: () => { this.detail = inv; this.cancelReason = ''; },
    });
  }

  closeDetail() { this.detail = null; this.cancelReason = ''; }

  confirmCancel() {
    if (!this.detail) return;
    const id = this.detail.id;
    this.recruitment.cancelInvitation(id, this.cancelReason).subscribe({
      next: () => {
        this.showToast('Invitation annulée. Le candidat a été notifié.');
        this.closeDetail();
        this.load();
      },
      error: err => this.showToast(err?.error?.detail || 'Erreur lors de l\'annulation.'),
    });
  }

  // ── Copy invitation link ──
  copyLink(url: string, token: string) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(url).then(() => {
      this.copiedToken = token;
      this.showToast('Lien copié dans le presse-papier ✓');
      setTimeout(() => { if (this.copiedToken === token) this.copiedToken = null; }, 2500);
    });
  }

  showToast(msg: string) {
    this.toastMsg = msg;
    setTimeout(() => { if (this.toastMsg === msg) this.toastMsg = ''; }, 3500);
  }

  // ── Formatters ──
  formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }

  formatDate(iso: string): string {
    const d = new Date(iso);
    const days = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
    const months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
    return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
  }

  formatFull(iso: string): string {
    return `${this.formatDate(iso)} ${new Date(iso).getFullYear()} · ${this.formatTime(iso)}`;
  }

  daysAgo(iso: string): string {
    const ms = Date.now() - new Date(iso).getTime();
    const days = Math.floor(ms / 86400000);
    if (days <= 0) return "Aujourd'hui";
    if (days === 1) return 'Hier';
    if (days < 7) return `Il y a ${days} jours`;
    if (days < 30) return `Il y a ${Math.floor(days / 7)} sem.`;
    return `Il y a ${Math.floor(days / 30)} mois`;
  }

  expiresIn(iso: string): string {
    const ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return 'expiré';
    const h = Math.floor(ms / 3_600_000);
    const m = Math.floor((ms % 3_600_000) / 60_000);
    if (h >= 24) return `${Math.floor(h / 24)} j`;
    if (h > 0)   return `${h}h${m.toString().padStart(2, '0')}`;
    return `${m} min`;
  }

  durationMin(start: string, end: string): number {
    return Math.round((+new Date(end) - +new Date(start)) / 60000);
  }

  statusLabel(s: InvitationStatus): string {
    switch (s) {
      case 'PENDING':   return 'En attente';
      case 'CONFIRMED': return 'Confirmé';
      case 'EXPIRED':   return 'Expiré';
      case 'CANCELLED': return 'Annulé';
    }
  }


  // ── Lien de visioconférence ─────────────────────────────────────────────

  /**
   * Le lien visio a-t-il encore une raison d'être proposé ?
   *
   * Il reste une journée après la fin de l'entretien, puis disparaît. Le
   * proposer indéfiniment donne un bouton qui ne mène nulle part — la salle
   * est vide et le RH clique pour rien.
   *
   * Pourquoi une journée et non la fin du créneau : une connexion qui lâche,
   * un entretien qui déborde, un participant qui rejoint en retard. Couper net
   * à l'heure dite retirerait le lien au moment précis où il sert encore.
   */
  lienVisioUtile(inv: InvitationResponse): boolean {
    if (!inv.meet_url) return false;
    const slot = this.confirmedSlotOf(inv);
    // Pas de créneau retenu : on ne sait pas si le lien est périmé, donc on le
    // garde. Retirer par précaution supprimerait une fonction qui marche.
    if (!slot) return true;
    return Date.now() < new Date(slot.end_at).getTime() + VISIO_DUREE_DE_VIE_MS;
  }

  // ── Évaluation d'entretien ──────────────────────────────────────────────

  /**
   * L'entretien a-t-il eu lieu ?
   *
   * On se cale sur la FIN du créneau, pas sur son début : proposer d'évaluer
   * pendant que le rendez-vous se déroule encore invite à noter quelqu'un
   * qu'on est en train d'écouter.
   */
  entretienPasse(inv: InvitationResponse): boolean {
    if (inv.status !== 'CONFIRMED') return false;
    const slot = this.confirmedSlotOf(inv);
    if (!slot) return false;
    return new Date(slot.end_at).getTime() <= Date.now();
  }

  ouvrirEvaluation(inv: InvitationResponse, event?: Event) {
    event?.stopPropagation();
    this.evaluationApplicationId = inv.application_id;
    this.evaluationCandidat = inv.candidate_name || 'ce candidat';
  }

  fermerEvaluation() {
    this.evaluationApplicationId = null;
  }

  surEvaluationEnregistree() {
    this.showToast('Évaluation enregistrée — le score composite est à jour.');
  }

  confirmedSlotOf(inv: InvitationResponse) {
    return inv.slots.find(s => s.is_selected) || null;
  }
}
