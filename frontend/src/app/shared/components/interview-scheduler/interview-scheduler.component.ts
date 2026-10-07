import { Component, Input, Output, EventEmitter, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { EMPTY, Subscription, expand, reduce } from 'rxjs';
import {
  Application,
  JOB_STATUS_LABELS,
  JobOffer,
  RecruitmentService,
  canTransitionStatus,
} from '../../../core/services/recruitment.service';
import { UserService } from '../../../core/services/user.service';
import { AuthService } from '../../../core/services/auth.service';
import { SelectComponent, SelectOption } from '../select/select.component';

interface RecruiterOption {
  id: string;
  label: string;
  email: string;
}

/** Taille de page maximale acceptée par l'API pour lister offres et candidatures. */
const TAILLE_PAGE = 100;

@Component({
  selector: 'app-interview-scheduler',
  standalone: true,
  imports: [CommonModule, FormsModule, SelectComponent],
  templateUrl: './interview-scheduler.component.html',
  styleUrl: './interview-scheduler.component.css'
})
export class InterviewSchedulerComponent implements OnInit, OnDestroy {
  @Input() applicationId: string = '';
  @Input() jobTitle: string = '';
  /**
   * Texte proposé dans la zone de message, que le RH relit et modifie avant
   * d'envoyer. Vide par défaut : les écrans qui n'en fournissent pas gardent
   * le champ libre qu'ils avaient.
   */
  @Input() prefillMessage: string = '';

  /**
   * Sans candidature imposée par l'écran appelant : le RH choisit l'offre, puis
   * l'un de ses candidats. Les écrans qui planifient depuis une candidature
   * déjà ouverte gardent `applicationId` et n'affichent rien de plus.
   */
  @Input() selectionCandidat = false;

  @Output() closed = new EventEmitter<boolean>();

  // ── Offre puis candidat (mode `selectionCandidat`) ────────────────────────
  // Des CHAMPS, pas des getters : `app-select` compare ses options par
  // identité, et un tableau neuf à chaque cycle de détection le ferait boucler.
  offreOptions: SelectOption[] = [];
  offreId = '';
  offresChargement = false;
  offresErreur = '';

  candidatOptions: SelectOption[] = [];
  candidatureId = '';
  candidaturesChargement = false;
  candidaturesErreur = '';
  /** Dossiers de l'offre qu'on ne propose pas (clos ou déjà acceptés). */
  nbNonPlanifiables = 0;
  private candidaturesSub?: Subscription;

  slots: string[] = ['', '', ''];
  message = '';
  isSubmitting = false;
  success = false;
  errorMsg = '';

  // ── Membres de l'entretien ────────────────────────────────────────────────
  // Ceux qui mènent l'entretien : ils sont prévenus, et seuls eux pourront
  // l'évaluer. Un recruteur ne voit que les entretiens dont il est membre.
  recruiters: RecruiterOption[] = [];
  membres: RecruiterOption[] = [];
  /** Options du sélecteur : le personnel pas encore ajouté. Un champ, pas un getter. */
  recruteurOptions: SelectOption[] = [];
  /** Valeur transitoire du sélecteur : remise à vide dès qu'un membre est ajouté. */
  membreAAjouter = '';

  // ── Lien de visioconférence ───────────────────────────────────────────────
  // Figé dès la planification quand le RH en génère un, plutôt qu'à la
  // confirmation : le lien peut ainsi être communiqué à l'avance.
  meetUrl = '';
  meetGeneration = false;
  meetErreur = '';
  /** Ce qui a réellement été produit — affiché tel quel, sans promettre Meet. */
  meetProvider = '';
  /** Vrai quand le compte Google de l'utilisateur est lié à l'API Meet. */
  googleMeetLinked = false;
  /** Raison remontée par Google en cas de refus (API non activée, portée…). */
  googleMeetErreur = '';
  /** Faux si aucun client OAuth n'est déclaré côté serveur. */
  googleMeetConfigure = true;
  connexionGoogleEnCours = false;

  private userService = inject(UserService);
  private auth = inject(AuthService);

  constructor(private recruitment: RecruitmentService) {}

  ngOnInit(): void {
    if (this.prefillMessage) this.message = this.prefillMessage;
    this._loadRecruiters();
    if (this.selectionCandidat) this._loadOffres();
  }

  ngOnDestroy(): void {
    this.candidaturesSub?.unsubscribe();
  }

  /** La candidature visée : celle imposée par l'écran, ou celle qu'on a choisie. */
  get cibleId(): string {
    return this.selectionCandidat ? this.candidatureId : this.applicationId;
  }

  get placeholderOffre(): string {
    if (this.offresChargement) return 'Chargement…';
    return this.offreOptions.length ? 'Choisir une offre' : 'Aucune offre';
  }

  get placeholderCandidat(): string {
    if (!this.offreId) return "Choisissez d'abord une offre";
    if (this.candidaturesChargement) return 'Chargement…';
    if (!this.candidatOptions.length) return 'Aucun candidat à inviter';
    return 'Choisir un candidat';
  }

  /**
   * Toutes les offres, page par page : l'API plafonne à 100, et s'arrêter à la
   * première page ferait disparaître des offres sans que rien ne le signale.
   * Les brouillons sont écartés — personne n'y a encore postulé.
   */
  private _loadOffres(): void {
    this.offresChargement = true;
    const page = (n: number) => this.recruitment.getJobsForManagement(n, TAILLE_PAGE);
    page(1).pipe(
      expand(res => (res.page * res.size < res.total ? page(res.page + 1) : EMPTY)),
      reduce((acc, res) => acc.concat(res.items), [] as JobOffer[]),
    ).subscribe({
      next: (items) => {
        this.offreOptions = items
          .filter(o => o.status !== 'DRAFT')
          .map(o => ({
            value: o.id,
            label: o.status && o.status !== 'PUBLISHED'
              ? `${o.title} (${JOB_STATUS_LABELS[o.status]})`
              : o.title,
          }));
        this.offresChargement = false;
      },
      error: (err) => {
        this.offresChargement = false;
        this.offresErreur = err?.error?.detail || "Les offres n'ont pas pu être chargées.";
      },
    });
  }

  choisirOffre(offreId: string): void {
    this.offreId = offreId;
    this.candidatureId = '';
    this.candidatOptions = [];
    this.nbNonPlanifiables = 0;
    this.candidaturesErreur = '';
    this.candidaturesSub?.unsubscribe();
    if (!offreId) return;

    // `/jobs/{id}/applications` ne renvoie que les 20 plus récentes : on passe
    // par la liste paginée pour ne perdre aucun candidat.
    this.candidaturesChargement = true;
    const page = (n: number) => this.recruitment.getApplications(offreId, n, TAILLE_PAGE);
    this.candidaturesSub = page(1).pipe(
      expand((items, index) => (items.length === TAILLE_PAGE ? page(index + 2) : EMPTY)),
      reduce((acc, items) => acc.concat(items), [] as Application[]),
    ).subscribe({
      next: (apps) => {
        // Même règle que le serveur : un dossier clos ou déjà accepté ne repart
        // pas en entretien. On ne le propose donc pas, et on dit combien on en
        // a écartés pour qu'on ne cherche pas un candidat qui est bien là.
        const planifiables = apps.filter(a => canTransitionStatus(a.status, 'INTERVIEW_SCHEDULED'));
        this.nbNonPlanifiables = apps.length - planifiables.length;
        this.candidatOptions = planifiables.map(a => ({
          value: a.id,
          label: a.candidate_name || 'Candidat',
        }));
        this.candidaturesChargement = false;
      },
      error: (err) => {
        this.candidaturesChargement = false;
        this.candidaturesErreur = err?.error?.detail || "Les candidats n'ont pas pu être chargés.";
      },
    });
  }

  private _loadRecruiters(): void {
    this.userService.listUsers({ size: 100 }).subscribe({
      next: (res) => {
        this.recruiters = res.items
          .filter(u => ['ADMIN', 'RH', 'RECRUTEUR'].includes(u.role ?? ''))
          .map(u => ({
            id: u.id,
            label: u.full_name || u.username || u.email,
            email: u.email,
          }));
        // Qui planifie un entretien en fait d'ordinaire partie : on le
        // propose d'emblée, il peut se retirer.
        const moi = this.auth.getCurrentUser();
        const soi = moi && this.recruiters.find(r => r.id === moi.id);
        if (soi && !this.membres.length) this.membres = [soi];
        this.majOptionsMembres();
      },
      error: () => { /* non-blocking: recruiter field stays hidden */ },
    });
  }

  ajouterMembre(id: string): void {
    const r = this.recruiters.find(x => x.id === id);
    if (r && !this.membres.some(m => m.id === id)) this.membres = [...this.membres, r];
    // Le sélecteur redevient vide, prêt pour le membre suivant.
    this.membreAAjouter = '';
    this.majOptionsMembres();
  }

  retirerMembre(id: string): void {
    this.membres = this.membres.filter(m => m.id !== id);
    this.majOptionsMembres();
  }

  private majOptionsMembres(): void {
    // Un CHAMP, pas un getter : `app-select` compare ses options par identité.
    this.recruteurOptions = this.recruiters
      .filter(r => !this.membres.some(m => m.id === r.id))
      .map(r => ({ value: r.id, label: `${r.label} <${r.email}>` }));
  }

  genererLienVisio(): void {
    this.meetErreur = '';
    this.meetGeneration = true;
    this.recruitment.generateMeetLink().subscribe({
      next: (res) => {
        this.meetGeneration = false;
        this.meetUrl = res.meet_url;
        this.meetProvider = res.provider;
        this.googleMeetLinked = true;
        this.googleMeetErreur = '';
        this.meetErreur = '';
      },
      error: (err) => {
        this.meetGeneration = false;
        this.meetErreur = err?.error?.detail || 'Génération du lien impossible.';
        // 409 = compte Google non lié. C'est le seul cas où proposer la
        // connexion a du sens : un 502 vient de Google, se reconnecter n'y
        // changerait rien.
        this.googleMeetLinked = err?.status !== 409;
      },
    });
  }

  /**
   * Ouvre le consentement Google dans un onglet.
   *
   * Au retour, Google redirige vers le back-office : l'utilisateur revient
   * dans l'application, pas dans cette modale. Il rouvre alors la
   * planification et regénère le lien — qui sera cette fois un vrai Meet.
   */
  connecterGoogleMeet(): void {
    this.connexionGoogleEnCours = true;
    this.recruitment.getGoogleMeetAuthorizeUrl().subscribe({
      next: (res) => {
        this.connexionGoogleEnCours = false;
        window.open(res.authorize_url, '_blank', 'noopener');
      },
      error: (err) => {
        this.connexionGoogleEnCours = false;
        this.meetErreur = err?.error?.detail
          || 'Connexion Google impossible : client OAuth non configuré.';
      },
    });
  }

  copierLienVisio(): void {
    if (!this.meetUrl) return;
    navigator.clipboard?.writeText(this.meetUrl);
  }

  addSlot() {
    if (this.slots.length < 5) this.slots.push('');
  }

  removeSlot(i: number) {
    if (this.slots.length > 1) this.slots.splice(i, 1);
  }

  get validSlots(): string[] {
    return this.slots.filter(s => s.trim().length > 0);
  }

  trackByIndex(i: number) { return i; }

  submit() {
    if (!this.cibleId) {
      this.errorMsg = 'Choisissez le candidat à inviter.';
      return;
    }
    if (this.validSlots.length === 0) {
      this.errorMsg = 'Veuillez saisir au moins un créneau.';
      return;
    }
    this.isSubmitting = true;
    this.errorMsg = '';

    const isoSlots = this.validSlots.map(s => new Date(s).toISOString());

    this.recruitment.scheduleInterview(
      this.cibleId,
      isoSlots,
      this.message,
      30,
      48,
      this.membres.map(m => m.id),
      this.meetUrl.trim() || null,
    ).subscribe({
      next: () => {
        this.isSubmitting = false;
        this.success = true;
        setTimeout(() => this.closed.emit(true), 1600);
      },
      error: (err) => {
        this.isSubmitting = false;
        this.errorMsg = err?.error?.detail || 'Erreur lors de la planification.';
      }
    });
  }

  cancel() { this.closed.emit(false); }
}
