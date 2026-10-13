import { Component, DestroyRef, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, debounceTime, distinctUntilChanged, forkJoin } from 'rxjs';
import {
  UserService, AuditLog, AuditCategory, PaginatedAuditLogs,
} from '../../../core/services/user.service';
import { AuthService } from '../../../core/services/auth.service';
import { roleLabel } from '../../../core/models/user.model';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';
import { PaginationComponent } from '../../../shared/components/pagination/pagination.component';

type Tone = 'success' | 'danger' | 'warn' | 'info' | 'neutral';
type Onglet = 'journal' | 'historique';

/** Libellé lisible et couleur de chaque code d'action écrit par le serveur. */
const ACTIONS: Record<string, { label: string; tone: Tone }> = {
  LOGIN_SUCCESS:              { label: 'Connexion réussie', tone: 'success' },
  LOGIN_SUCCESS_GOOGLE:       { label: 'Connexion via Google', tone: 'success' },
  LOGIN_SUCCESS_BACKUP_CODE:  { label: 'Connexion par code de secours', tone: 'success' },
  LOGIN_SUCCESS_AFTER_VERIFY: { label: 'Connexion après vérification de l’e-mail', tone: 'success' },
  LOGIN_FAIL:                 { label: 'Échec de connexion', tone: 'danger' },
  LOGIN_FAIL_2FA:             { label: 'Code de double authentification refusé', tone: 'danger' },
  BACKUP_CODE_FAIL:           { label: 'Code de secours refusé', tone: 'danger' },
  BACKUP_CODE_USED:           { label: 'Code de secours utilisé', tone: 'warn' },
  LOGOUT:                     { label: 'Déconnexion', tone: 'neutral' },
  TOKEN_REFRESH:              { label: 'Session renouvelée', tone: 'neutral' },
  REGISTER:                   { label: 'Inscription', tone: 'info' },
  GOOGLE_REGISTER:            { label: 'Inscription via Google', tone: 'info' },
  GOOGLE_LINKED:              { label: 'Compte Google associé', tone: 'info' },
  EMAIL_VERIFIED:             { label: 'E-mail vérifié', tone: 'success' },
  EMAIL_VERIFY_FAIL:          { label: 'Échec de vérification de l’e-mail', tone: 'danger' },
  EMAIL_VERIFY_RESEND:        { label: 'Code de vérification renvoyé', tone: 'neutral' },
  PASSWORD_RESET_REQUEST:     { label: 'Réinitialisation du mot de passe demandée', tone: 'warn' },
  PASSWORD_RESET:             { label: 'Mot de passe réinitialisé', tone: 'warn' },
  PASSWORD_CHANGE:            { label: 'Mot de passe modifié', tone: 'warn' },
  TOTP_SETUP_INIT:            { label: 'Configuration de la double authentification', tone: 'info' },
  TOTP_ENABLED:               { label: 'Double authentification activée', tone: 'success' },
  TOTP_DISABLED:              { label: 'Double authentification désactivée', tone: 'warn' },
  TOTP_RESET:                 { label: 'Double authentification réinitialisée', tone: 'warn' },
  USER_UPDATE_SELF:           { label: 'Profil modifié', tone: 'info' },
  USER_ADMIN_UPDATE:          { label: 'Compte modifié par l’administration', tone: 'info' },
  USER_DELETE:                { label: 'Compte supprimé', tone: 'danger' },
  // Corrections réservées à l'administrateur — le motif est dans le détail.
  CONTRACT_WITHDRAWN:         { label: 'Contrat retiré par l’administration', tone: 'danger' },
  APPLICATION_STATUS_FORCED:  { label: 'Statut de candidature corrigé par l’administration', tone: 'warn' },
};

/** Les lignes d'un même jour, sous un intitulé « Aujourd'hui », « Hier » ou une date. */
interface GroupeJour {
  jour: string;
  lignes: AuditLog[];
}

const FMT_JOUR = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const FMT_HEURE = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/**
 * Journal d'audit de la plateforme, en deux onglets :
 *  - « Journal d'audit » : toutes les actions sensibles, tous comptes
 *    confondus, filtrables (recherche, catégorie, échecs) ;
 *  - « Historique d'activité » : les actions du compte connecté.
 * La page ne fait que lire : le journal est écrit par le serveur seul.
 */
@Component({
  selector: 'app-audit-log',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, SelectComponent, PaginationComponent],
  templateUrl: './audit-log.component.html',
  styleUrls: ['./audit-log.component.css'],
})
export class AuditLogComponent implements OnInit {
  onglet: Onglet = 'journal';

  readonly categories: SelectOption[] = [
    { value: '', label: 'Toutes les catégories' },
    { value: 'connexions', label: 'Connexions' },
    { value: 'securite', label: 'Sécurité' },
    { value: 'comptes', label: 'Comptes' },
  ];

  // ── Onglet « Journal d'audit » ──
  recherche = '';
  categorie: AuditCategory | '' = '';
  echecsSeulement = false;
  avecRenouvellements = false;
  journal: AuditLog[] = [];
  journalGroupes: GroupeJour[] = [];
  journalTotal = 0;
  journalPage = 1;
  journalTaille = 25;
  journalChargement = false;
  journalErreur = '';

  // ── Onglet « Historique d'activité » ──
  historiqueCategorie: AuditCategory | '' = '';
  historiqueGroupes: GroupeJour[] = [];
  historiqueTotal = 0;
  historiquePage = 1;
  readonly historiqueTaille = 15;
  historiqueChargement = false;
  historiqueErreur = '';
  private historiqueCharge = false;

  // ── Synthèse (en-tête) ──
  synthese: { total: number; echecs: number; connexions: number } | null = null;

  private readonly recherche$ = new Subject<string>();

  constructor(
    private users: UserService,
    private auth: AuthService,
    private destroyRef: DestroyRef,
  ) {}

  ngOnInit(): void {
    this.recherche$
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => { this.journalPage = 1; this.chargerJournal(); });
    this.chargerSynthese();
    this.chargerJournal();
  }

  get nomConnecte(): string {
    return this.auth.getCurrentUser()?.full_name || 'votre compte';
  }

  get journalPages(): number {
    return Math.max(1, Math.ceil(this.journalTotal / this.journalTaille));
  }

  get historiquePages(): number {
    return Math.max(1, Math.ceil(this.historiqueTotal / this.historiqueTaille));
  }

  get filtresActifs(): boolean {
    return !!this.recherche.trim() || !!this.categorie || this.echecsSeulement || this.avecRenouvellements;
  }

  changerOnglet(onglet: Onglet): void {
    this.onglet = onglet;
    if (onglet === 'historique' && !this.historiqueCharge) this.chargerHistorique();
  }

  // ── Journal ──

  surRecherche(valeur: string): void {
    this.recherche$.next(valeur.trim());
  }

  surFiltre(): void {
    this.journalPage = 1;
    this.chargerJournal();
  }

  basculerEchecs(): void {
    this.echecsSeulement = !this.echecsSeulement;
    this.surFiltre();
  }

  basculerRenouvellements(): void {
    this.avecRenouvellements = !this.avecRenouvellements;
    this.surFiltre();
  }

  reinitialiser(): void {
    this.recherche = '';
    this.recherche$.next('');
    this.categorie = '';
    this.echecsSeulement = false;
    this.avecRenouvellements = false;
    this.surFiltre();
  }

  allerPageJournal(page: number): void {
    this.journalPage = page;
    this.chargerJournal();
  }

  changerTailleJournal(taille: number): void {
    this.journalTaille = taille;
    this.journalPage = 1;
    this.chargerJournal();
  }

  private chargerJournal(): void {
    this.journalChargement = true;
    this.journalErreur = '';
    this.users.getAuditLogs({
      category: this.categorie,
      search: this.recherche,
      failuresOnly: this.echecsSeulement,
      includeRefresh: this.avecRenouvellements,
    }, this.journalPage, this.journalTaille).subscribe({
      next: res => {
        this.journal = res.items;
        this.journalGroupes = this.grouperParJour(res.items);
        this.journalTotal = res.total;
        this.journalChargement = false;
      },
      error: () => {
        this.journal = [];
        this.journalGroupes = [];
        this.journalTotal = 0;
        this.journalChargement = false;
        this.journalErreur = 'Impossible de charger le journal d’audit.';
      },
    });
  }

  /** Trois compteurs en tête de page : une requête d'une ligne chacun, seul `total` sert. */
  private chargerSynthese(): void {
    forkJoin({
      total: this.users.getAuditLogs({}, 1, 1),
      echecs: this.users.getAuditLogs({ failuresOnly: true }, 1, 1),
      connexions: this.users.getAuditLogs({ category: 'connexions' }, 1, 1),
    }).subscribe({
      next: (r: Record<'total' | 'echecs' | 'connexions', PaginatedAuditLogs>) => this.synthese = {
        total: r.total.total, echecs: r.echecs.total, connexions: r.connexions.total,
      },
      error: () => this.synthese = null,
    });
  }

  // ── Historique ──

  filtrerHistorique(categorie: AuditCategory | ''): void {
    if (this.historiqueCategorie === categorie) return;
    this.historiqueCategorie = categorie;
    this.historiquePage = 1;
    this.chargerHistorique();
  }

  allerPageHistorique(page: number): void {
    this.historiquePage = page;
    this.chargerHistorique();
  }

  private chargerHistorique(): void {
    this.historiqueChargement = true;
    this.historiqueErreur = '';
    this.users.getMyAuditLogs(this.historiquePage, this.historiqueTaille, this.historiqueCategorie).subscribe({
      next: res => {
        this.historiqueGroupes = this.grouperParJour(res.items);
        this.historiqueTotal = res.total;
        this.historiqueChargement = false;
        this.historiqueCharge = true;
      },
      error: () => {
        this.historiqueGroupes = [];
        this.historiqueTotal = 0;
        this.historiqueChargement = false;
        this.historiqueErreur = 'Impossible de charger votre historique d’activité.';
      },
    });
  }

  // ── Présentation ──

  libelle(action: string): string {
    return ACTIONS[action]?.label ?? action.replace(/_/g, ' ').toLowerCase();
  }

  ton(action: string): Tone {
    return ACTIONS[action]?.tone ?? 'neutral';
  }

  heure(iso: string): string {
    return FMT_HEURE.format(new Date(iso));
  }

  /** L'adresse IP est en colonne ; certaines lignes ne l'ont que dans `details`. */
  ip(log: AuditLog): string {
    return log.ip_address || (typeof log.details?.['ip'] === 'string' ? log.details['ip'] : '') || '—';
  }

  role(log: AuditLog): string {
    return roleLabel(log.user_role) || '—';
  }

  /** Action menée sur un AUTRE compte, encore consultable : on propose d'ouvrir sa fiche. */
  cibleConsultable(log: AuditLog): boolean {
    return log.resource === 'user' && !!log.resource_id
      && log.resource_id !== log.user_id && log.action !== 'USER_DELETE';
  }

  trackById(_: number, log: AuditLog): string {
    return log.id;
  }

  private grouperParJour(logs: AuditLog[]): GroupeJour[] {
    const groupes: GroupeJour[] = [];
    for (const log of logs) {
      const jour = this.intituleJour(new Date(log.created_at));
      const dernier = groupes[groupes.length - 1];
      if (dernier?.jour === jour) dernier.lignes.push(log);
      else groupes.push({ jour, lignes: [log] });
    }
    return groupes;
  }

  private intituleJour(date: Date): string {
    const debut = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const ecart = Math.round((debut(new Date()) - debut(date)) / 86_400_000);
    if (ecart === 0) return 'Aujourd’hui';
    if (ecart === 1) return 'Hier';
    const texte = FMT_JOUR.format(date);
    return texte.charAt(0).toUpperCase() + texte.slice(1);
  }
}
