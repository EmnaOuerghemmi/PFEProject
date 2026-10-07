import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { InterviewEvaluationComponent } from '../../../shared/components/interview-evaluation/interview-evaluation.component';
import { InterviewSchedulerComponent } from '../../../shared/components/interview-scheduler/interview-scheduler.component';
import {
  RecruitmentService,
  InvitationResponse,
  InvitationStatus,
  CalendarSlot,
  canTransitionStatus,
} from '../../../core/services/recruitment.service';
import { CandidateEvaluation } from '../../../core/services/assessment.service';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';

/**
 * Onglets par ÉTAPE de l'entretien (calculée par le serveur), et non par
 * statut d'invitation : « confirmé » mêlait l'entretien de demain et celui
 * d'il y a trois semaines.
 */
type Onglet = 'A_VENIR' | 'PASSES' | 'EN_ATTENTE' | 'ANNULES';
type SousOnglet = 'A_EVALUER' | 'EVALUES';

/** Tri des cartes : par proximité de la date (défaut), à l'envers, ou par nom. */
type Tri = 'PROCHE' | 'ELOIGNE' | 'NOM';

/** Ce que propose la fenêtre qui suit une évaluation. */
interface SuiteEvaluation {
  applicationId: string;
  jobOfferId: string | null;
  candidat: string;
  note: number | null;
  /** Le passage à « Acceptée » est-il encore possible ? */
  acceptable: boolean;
  acceptee: boolean;
}

/**
 * Combien de temps le lien de visioconférence reste proposé après la fin de
 * l'entretien. Au-delà, la salle est vide : le bouton ne mènerait nulle part.
 */
const VISIO_DUREE_DE_VIE_MS = 24 * 60 * 60 * 1000;

@Component({
  selector: 'app-interview-manager',
  standalone: true,
  imports: [CommonModule, FormsModule, InterviewEvaluationComponent, InterviewSchedulerComponent, SelectComponent],
  templateUrl: './interview-manager.component.html',
  styleUrl: './interview-manager.component.css',
})
export class InterviewManagerComponent implements OnInit {
  // Data
  invitations: InvitationResponse[] = [];
  filtered: InvitationResponse[] = [];

  // Pagination — quatre cartes par page, dans chaque onglet.
  pageSize = 4;
  currentPage = 1;

  get pagedFiltered(): InvitationResponse[] {
    const start = (this.currentPage - 1) * this.pageSize;
    return this.filtered.slice(start, start + this.pageSize);
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.filtered.length / this.pageSize));
  }

  /** « 5–8 sur 9 » : la plage affichée sur la page courante. */
  get plageDebut(): number { return this.filtered.length ? (this.currentPage - 1) * this.pageSize + 1 : 0; }
  get plageFin(): number { return Math.min(this.currentPage * this.pageSize, this.filtered.length); }
  /** « 5–8 sur 9 », ou « 9 sur 9 » quand la dernière page ne porte qu'une carte. */
  get plageTexte(): string {
    const debut = this.plageDebut, fin = this.plageFin;
    return `${debut === fin ? fin : `${debut}–${fin}`} sur ${this.filtered.length}`;
  }

  prevPage() { if (this.currentPage > 1) this.currentPage--; }
  nextPage() { if (this.currentPage < this.totalPages) this.currentPage++; }

  // Filters / UI state — « À venir » s'ouvre par défaut.
  onglet: Onglet = 'A_VENIR';
  sousOnglet: SousOnglet = 'A_EVALUER';
  tri: Tri = 'PROCHE';
  /** Un champ, pas un getter : `app-select` compare ses options par identité. */
  readonly triOptions: SelectOption[] = [
    { value: 'PROCHE',  label: "Date : la plus proche d'abord" },
    { value: 'ELOIGNE', label: "Date : la plus éloignée d'abord" },
    { value: 'NOM',     label: 'Candidat : A → Z' },
  ];
  searchQuery = '';

  isLoading = false;
  errorMsg = '';

  // Selection / modals
  detail: InvitationResponse | null = null;
  cancelReason = '';
  copiedToken: string | null = null;
  toastMsg = '';

  // Compteurs (calculés depuis `invitations`)
  total = 0;
  countAVenir = 0;
  /** À évaluer PAR MOI : l'onglet est réservé aux membres de l'entretien. */
  countAEvaluer = 0;
  countEvalues = 0;
  countEnAttente = 0;
  countAnnulees = 0;
  /** Entretiens passés qui attendent l'évaluation d'AUTRES membres. */
  countAutresAEvaluer = 0;

  readonly onglets: { value: Onglet; label: string; tone: string }[] = [
    { value: 'A_VENIR',    label: 'À venir',               tone: 'success' },
    { value: 'PASSES',     label: 'Passés',                tone: 'all' },
    { value: 'EN_ATTENTE', label: 'En attente de réponse', tone: 'warn' },
    { value: 'ANNULES',    label: 'Annulées',              tone: 'danger' },
  ];
  readonly sousOnglets: { value: SousOnglet; label: string }[] = [
    { value: 'A_EVALUER', label: 'À évaluer' },
    { value: 'EVALUES',   label: 'Évalués' },
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
  /** L'entretien dont on ouvre l'évaluation — pour proposer la suite ensuite. */
  private evaluationInvitation: InvitationResponse | null = null;

  /** Fenêtre « et maintenant ? » ouverte après l'enregistrement d'une évaluation. */
  suite: SuiteEvaluation | null = null;
  acceptationEnCours = false;
  suiteErreur = '';

  /** Modale « Créer un entretien » : offre, puis candidat, puis créneaux. */
  planificationOuverte = false;

  // ── Google Calendar / ICS ──
  googleConfigured = false;
  syncingId: string | null = null;
  downloadingIcsId: string | null = null;

  constructor(private recruitment: RecruitmentService, private router: Router) {}

  ngOnInit() {
    this.weekStart = this.mondayOf(new Date());
    this.load();
    this.recruitment.getGoogleCalendarStatus().subscribe({
      next: (s) => (this.googleConfigured = s.configured),
      error: () => (this.googleConfigured = false),
    });
  }

  // ════════════ Création d'un entretien ════════════

  ouvrirPlanification(): void {
    this.planificationOuverte = true;
  }

  /** `planifie` : une invitation vient d'être envoyée — la liste doit la montrer. */
  fermerPlanification(planifie: boolean): void {
    this.planificationOuverte = false;
    if (!planifie) return;
    this.load();
    if (this.view === 'calendar') this.loadCalendar();
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
    const n = (f: (i: InvitationResponse) => boolean) => this.invitations.filter(f).length;
    this.total = this.invitations.length;
    this.countAVenir         = n(i => i.stage === 'A_VENIR');
    this.countAEvaluer       = n(i => i.stage === 'A_EVALUER' && i.can_evaluate);
    this.countAutresAEvaluer = n(i => i.stage === 'A_EVALUER' && !i.can_evaluate);
    this.countEvalues        = n(i => i.stage === 'EVALUE');
    this.countEnAttente      = n(i => i.stage === 'EN_ATTENTE');
    this.countAnnulees       = n(i => i.stage === 'ABSENT' || i.stage === 'ANNULE');
  }

  /** L'entretien appartient-il à l'onglet (et sous-onglet) affiché ? */
  private dansOnglet(inv: InvitationResponse): boolean {
    switch (this.onglet) {
      case 'A_VENIR':    return inv.stage === 'A_VENIR';
      case 'EN_ATTENTE': return inv.stage === 'EN_ATTENTE';
      case 'ANNULES':    return inv.stage === 'ABSENT' || inv.stage === 'ANNULE';
      case 'PASSES':
        return this.sousOnglet === 'EVALUES'
          ? inv.stage === 'EVALUE'
          // Réservé aux membres : ce sont eux qui ont mené l'entretien.
          : inv.stage === 'A_EVALUER' && inv.can_evaluate;
    }
  }

  /**
   * Date de référence d'une carte : celle que la carte met elle-même en avant.
   *
   * - entretien confirmé (à venir, à évaluer, évalué) : le rendez-vous ;
   * - invitation en attente : le premier créneau proposé ;
   * - absent ou annulé : la date qui figure au pied de la carte.
   */
  private dateDeTri(inv: InvitationResponse): number {
    const t = (iso: string) => new Date(iso).getTime();
    switch (inv.stage) {
      case 'A_VENIR':
      case 'A_EVALUER':
      case 'EVALUE': {
        const slot = this.confirmedSlotOf(inv);
        return t(slot ? slot.start_at : inv.created_at);
      }
      case 'EN_ATTENTE':
        return inv.slots.length ? Math.min(...inv.slots.map(s => t(s.start_at))) : t(inv.expires_at);
      case 'ABSENT':
        return t(inv.created_at);
      case 'ANNULE':
        return t(inv.cancelled_at || inv.updated_at);
    }
  }

  /**
   * « Proche » se mesure à aujourd'hui : un entretien à venir se range du plus
   * imminent au plus lointain, un entretien passé du plus récent au plus ancien.
   * Chaque onglet ne contient que des dates d'un même côté de maintenant, donc
   * la même règle sert partout.
   */
  private comparer(a: InvitationResponse, b: InvitationResponse): number {
    const nom = (i: InvitationResponse) => i.candidate_name || '';
    const parNom = nom(a).localeCompare(nom(b), 'fr', { sensitivity: 'base' });
    if (this.tri === 'NOM') return parNom;
    const maintenant = Date.now();
    const ecartA = Math.abs(this.dateDeTri(a) - maintenant);
    const ecartB = Math.abs(this.dateDeTri(b) - maintenant);
    const ecart = this.tri === 'PROCHE' ? ecartA - ecartB : ecartB - ecartA;
    return ecart || parNom;   // à égalité de date, l'ordre alphabétique est stable
  }

  rebuild() {
    const q = this.searchQuery.trim().toLowerCase();
    this.filtered = this.invitations
      .filter(inv => {
        if (!this.dansOnglet(inv)) return false;
        if (!q) return true;
        const hay = [inv.candidate_name, inv.candidate_email, inv.job_title,
                     ...(inv.members ?? []).map(m => m.name)]
          .filter(Boolean).join(' ').toLowerCase();
        return hay.includes(q);
      })
      .sort((a, b) => this.comparer(a, b));
    this.currentPage = 1;
  }

  // ── Filter handlers ──
  selectTab(t: Onglet) {
    this.onglet = t;
    this.rebuild();
  }

  selectSousOnglet(s: SousOnglet) {
    this.sousOnglet = s;
    this.rebuild();
  }

  onSearchChange() { this.rebuild(); }

  changerTri(tri: Tri) {
    this.tri = tri;
    this.rebuild();
  }

  countFor(t: Onglet): number {
    switch (t) {
      case 'A_VENIR':    return this.countAVenir;
      case 'PASSES':     return this.countAEvaluer + this.countEvalues;
      case 'EN_ATTENTE': return this.countEnAttente;
      case 'ANNULES':    return this.countAnnulees;
    }
  }

  countForSous(s: SousOnglet): number {
    return s === 'A_EVALUER' ? this.countAEvaluer : this.countEvalues;
  }

  get messageVide(): string {
    switch (this.onglet) {
      case 'A_VENIR':    return 'Aucun entretien à venir.';
      case 'EN_ATTENTE': return 'Aucune invitation en attente de réponse.';
      case 'ANNULES':    return 'Aucun entretien annulé ces 30 derniers jours.';
      case 'PASSES':
        return this.sousOnglet === 'EVALUES'
          ? 'Aucun entretien évalué pour le moment.'
          : 'Aucun entretien à évaluer de votre part.';
    }
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

  // ── Présentation des cartes ─────────────────────────────────────────────

  /** L'entretien a un rendez-vous fixé : à venir, à évaluer ou évalué. */
  aUnRendezVous(inv: InvitationResponse): boolean {
    return inv.stage === 'A_VENIR' || inv.stage === 'A_EVALUER' || inv.stage === 'EVALUE';
  }

  jourCourt(iso: string): string {
    return ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'][new Date(iso).getDay()];
  }

  jourNum(iso: string): number { return new Date(iso).getDate(); }

  annee(iso: string): number { return new Date(iso).getFullYear(); }

  /** Mois de la tuile ; l'année n'y figure que si ce n'est pas l'année en cours. */
  moisTuile(iso: string): string {
    const d = new Date(iso);
    const mois = this.monthShort(d);
    return d.getFullYear() === new Date().getFullYear() ? mois : `${mois} ${d.getFullYear()}`;
  }

  /**
   * Repère de temps au pied de la carte — une seule phrase, celle qui compte à
   * cette étape : dans combien de temps, depuis quand, jusqu'à quand.
   */
  repereTemps(inv: InvitationResponse): string {
    const slot = this.confirmedSlotOf(inv);
    const passe = (iso: string) => this.daysAgo(iso).toLowerCase();
    switch (inv.stage) {
      case 'A_VENIR':
        return this.enCours(inv) || !slot ? 'En cours' : `Dans ${this.expiresIn(slot.start_at)}`;
      case 'A_EVALUER':
        return slot ? `Terminé ${passe(slot.end_at)}` : '';
      case 'EVALUE':
        return inv.evaluated_at ? `Évalué ${passe(inv.evaluated_at)}` : 'Évalué';
      case 'EN_ATTENTE':
        return `Réponse sous ${this.expiresIn(inv.expires_at)}`;
      case 'ABSENT':
        return `Sans réponse · envoyée ${passe(inv.created_at)}`;
      case 'ANNULE':
        return `Annulé ${passe(inv.cancelled_at || inv.updated_at)}`;
    }
  }

  /** Libellé de l'étape, celui de la pastille. */
  stageLabel(inv: InvitationResponse): string {
    switch (inv.stage) {
      case 'A_VENIR':    return this.enCours(inv) ? 'En cours' : 'À venir';
      case 'A_EVALUER':  return 'À évaluer';
      case 'EVALUE':     return 'Évalué';
      case 'EN_ATTENTE': return 'En attente';
      case 'ABSENT':     return 'Candidat absent';
      case 'ANNULE':     return 'Annulé';
    }
  }

  /** Le rendez-vous a commencé et n'est pas fini. */
  enCours(inv: InvitationResponse): boolean {
    const slot = this.confirmedSlotOf(inv);
    if (!slot) return false;
    const maintenant = Date.now();
    return new Date(slot.start_at).getTime() <= maintenant && maintenant < new Date(slot.end_at).getTime();
  }

  /** Motif d'annulation lisible — le remplacement automatique était noté en anglais. */
  motifAnnulation(inv: InvitationResponse): string | null {
    if (!inv.cancellation_reason) return null;
    if (inv.cancellation_reason === 'Superseded by new invitation') return 'Remplacé par une nouvelle invitation';
    return inv.cancellation_reason;
  }

  nomsMembres(inv: InvitationResponse): string {
    return (inv.members ?? []).map(m => m.name).join(', ');
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
  // ── Lien de visioconférence ─────────────────────────────────────────────

  /** Invitation dont le lien est en cours de création. */
  meetEnCours: string | null = null;
  /** Message d'échec, par invitation. */
  meetErreurs: Record<string, string> = {};

  /**
   * Crée le lien de réunion et l'envoie au candidat et au recruteur assigné.
   *
   * Rattrapage : le lien est normalement produit dès la confirmation du
   * créneau. Ce bouton couvre les cas où cela n'a pas pu se faire.
   */
  genererLienMeet(inv: InvitationResponse, event: Event): void {
    event.stopPropagation();
    this.meetEnCours = inv.id;
    delete this.meetErreurs[inv.id];

    this.recruitment.createInvitationMeetLink(inv.id).subscribe({
      next: (res) => {
        this.meetEnCours = null;
        // Mise à jour sur place : recharger toute la liste ferait perdre la
        // pagination et les filtres en cours.
        inv.meet_url = res.meet_url;
        this.showToast(
          res.sent
            ? `Lien créé et envoyé à ${res.recipients ?? 0} destinataire(s).`
            : 'Lien créé.',
        );
      },
      error: (err) => {
        this.meetEnCours = null;
        this.meetErreurs[inv.id] =
          err?.error?.detail || 'Création du lien impossible.';
      },
    });
  }

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
    this.evaluationInvitation = inv;
    this.evaluationApplicationId = inv.application_id;
    this.evaluationCandidat = inv.candidate_name || 'ce candidat';
  }

  fermerEvaluation() {
    this.evaluationApplicationId = null;
  }

  /**
   * Après l'évaluation, l'étape suivante : accepter le candidat, ou aller
   * comparer sur la page Décision. L'entretien passe dans « Évalués ».
   */
  surEvaluationEnregistree(ev?: CandidateEvaluation) {
    const inv = this.evaluationInvitation;
    this.evaluationApplicationId = null;
    this.evaluationInvitation = null;
    this.load();
    if (!inv) return;
    const statut = inv.application_status;
    this.suiteErreur = '';
    this.suite = {
      applicationId: inv.application_id,
      jobOfferId: inv.job_offer_id,
      candidat: inv.candidate_name || 'ce candidat',
      note: ev?.interview_score ?? null,
      acceptable: statut !== 'ACCEPTED' && canTransitionStatus(statut, 'ACCEPTED'),
      acceptee: statut === 'ACCEPTED',
    };
  }

  fermerSuite() {
    this.suite = null;
  }

  accepterCandidat() {
    const suite = this.suite;
    if (!suite || !suite.acceptable) return;
    this.acceptationEnCours = true;
    this.suiteErreur = '';
    this.recruitment.updateApplication(suite.applicationId, 'ACCEPTED').subscribe({
      next: () => {
        this.acceptationEnCours = false;
        suite.acceptee = true;
        suite.acceptable = false;
        this.showToast(`${suite.candidat} est accepté(e).`);
        this.load();
      },
      error: (err) => {
        this.acceptationEnCours = false;
        this.suiteErreur = err?.error?.detail || "Le candidat n'a pas pu être accepté.";
      },
    });
  }

  ouvrirDecision() {
    const suite = this.suite;
    this.suite = null;
    this.router.navigate(['/admin/decision'], {
      queryParams: {
        ...(suite?.jobOfferId ? { offre: suite.jobOfferId } : {}),
        ...(suite ? { candidature: suite.applicationId } : {}),
      },
    });
  }

  confirmedSlotOf(inv: InvitationResponse) {
    return inv.slots.find(s => s.is_selected) || null;
  }
}
