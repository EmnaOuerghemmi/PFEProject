import { Component, OnInit, inject } from '@angular/core';
import { CommonModule, registerLocaleData } from '@angular/common';
import localeFr from '@angular/common/locales/fr';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import { UserService } from '../../../core/services/user.service';
import { Router } from '@angular/router';
import { TwoFactorComponent } from '../../auth/two-factor/two-factor.component';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { CandidateCv, RecruitmentService } from '../../../core/services/recruitment.service';

// Les dates de cette page demandent explicitement 'fr' : sans cette locale, les
// mois s'afficheraient en anglais (« October 2026 »). Elle n'est volontairement
// pas posée comme locale par défaut, pour ne rien changer aux autres pages.
registerLocaleData(localeFr);

/** Doit suivre `_MAX_SIZE` de l'envoi de photo côté backend. */
const PHOTO_MAX_OCTETS = 10 * 1024 * 1024;
const CV_MAX_OCTETS = 5 * 1024 * 1024;

/** Seuls les champs que l'API enregistre vraiment : nom et téléphone. */
interface UserProfile {
  email: string;
  full_name: string;
  username: string;
  phone: string;
  created_at?: string;
  avatar_url?: string | null;
}

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, TwoFactorComponent],
  templateUrl: './profile.component.html',
  styleUrls: ['./profile.component.css']
})
export class ProfileComponent implements OnInit {
  private toast = inject(ToastService);
  private confirmService = inject(ConfirmService);

  user: UserProfile | null = null;
  userInitial = '';
  originalUser: UserProfile | null = null;
  enregistrement = false;

  // ── Photo ─────────────────────────────────────────────────────────────────
  avatarEnvoi = false;
  avatarErreur = '';

  // ── CV de référence ────────────────────────────────────────────────────────
  // Déposé une fois, réutilisé à chaque candidature. Facultatif : un compte
  // sans CV reste parfaitement utilisable, la modale de candidature permettant
  // d'en joindre un à ce moment-là.
  private recruitment = inject(RecruitmentService);
  cv: CandidateCv | null = null;
  cvChargement = true;
  cvEnvoi = false;
  cvErreur = '';
  /**
   * L'état du CV n'a pas pu être lu. Distinct de `cvErreur`, qui sert aussi aux
   * dépôts refusés (format, document qui n'est pas un CV) : après un refus,
   * le bouton de dépôt doit rester là pour réessayer.
   */
  cvIndisponible = false;

  constructor(
    private authService: AuthService,
    private userService: UserService,
    private router: Router,
  ) {}

  ngOnInit() {
    this.chargerCv();
    const currentUser = this.authService.getCurrentUser();
    if (currentUser) {
      this.user = {
        email: currentUser.email,
        full_name: currentUser.full_name || '',
        username: currentUser.username || '',
        phone: currentUser.phone_number || '',
        created_at: currentUser.created_at,
        avatar_url: currentUser.avatar_url,
      };
      this.originalUser = { ...this.user };
      this.userInitial = (currentUser.full_name || currentUser.email).charAt(0).toUpperCase();
    } else {
      this.router.navigate(['/login']);
    }
  }

  /** Vrai dès qu'un champ du formulaire diffère de ce qui est enregistré. */
  get modifie(): boolean {
    return !!this.user && !!this.originalUser
      && (this.user.full_name !== this.originalUser.full_name
        || this.user.phone !== this.originalUser.phone);
  }

  saveProfile(): void {
    if (!this.user || !this.modifie || this.enregistrement) return;

    const nom = this.user.full_name.trim();
    if (!nom) {
      this.toast.error('Le nom ne peut pas être vide.');
      return;
    }

    this.enregistrement = true;
    this.userService.updateMe({
      full_name: nom,
      phone_number: this.user.phone.trim(),
    }).subscribe({
      next: (u) => {
        this.enregistrement = false;
        // Le nom du header et le reste de l'application suivent aussitôt.
        this.authService.updateCurrentUser(u);
        this.user = { ...this.user!, full_name: u.full_name || nom, phone: u.phone_number || '' };
        this.originalUser = { ...this.user };
        this.userInitial = (this.user.full_name || this.user.email).charAt(0).toUpperCase();
        this.toast.success('Modifications enregistrées.');
      },
      error: (err) => {
        this.enregistrement = false;
        this.toast.fromHttpError(err, "Impossible d'enregistrer pour le moment.");
      },
    });
  }

  resetForm(): void {
    if (this.originalUser) this.user = { ...this.originalUser };
  }

  surAvatarChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    const fichier = input.files?.[0];
    this.avatarErreur = '';
    input.value = '';
    if (!fichier) return;
    if (!['image/jpeg', 'image/jpg', 'image/png', 'image/webp'].includes(fichier.type)) {
      this.avatarErreur = 'Choisissez une image JPEG, PNG ou WebP.';
      return;
    }
    if (fichier.size > PHOTO_MAX_OCTETS) {
      this.avatarErreur = `Image trop lourde (${(fichier.size / 1048576).toFixed(1)} Mo, 10 Mo maximum).`;
      return;
    }
    this.avatarEnvoi = true;
    this.userService.uploadAvatar(fichier).subscribe({
      next: (u) => {
        this.avatarEnvoi = false;
        if (this.user) this.user.avatar_url = u.avatar_url;
        this.authService.updateCurrentUser(u);
        this.toast.success('Photo mise à jour.');
      },
      error: (err) => {
        this.avatarEnvoi = false;
        this.avatarErreur = err?.error?.detail || "La photo n'a pas pu être envoyée.";
      },
    });
  }

  chargerCv(): void {
    this.cvChargement = true;
    this.cvErreur = '';
    this.cvIndisponible = false;
    this.recruitment.getMyCv().subscribe({
      next: (cv) => { this.cv = cv; this.cvChargement = false; },
      error: (err) => {
        // Un échec ne doit pas se déguiser en « aucun CV » : le candidat
        // croirait devoir en redéposer un alors que le sien est peut-être
        // bien là, l'API simplement injoignable.
        this.cvChargement = false;
        this.cv = null;
        this.cvIndisponible = true;
        this.cvErreur = err?.status === 0
          ? 'Serveur injoignable.'
          : "Votre CV n'a pas pu être chargé.";
      },
    });
  }

  surCvChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    const fichier = input.files?.[0];
    this.cvErreur = '';
    if (!fichier) return;

    const extension = fichier.name.slice(fichier.name.lastIndexOf('.')).toLowerCase();
    if (!['.pdf', '.docx'].includes(extension)) {
      this.cvErreur = 'Format non accepté. Déposez un PDF ou un document Word (.docx).';
      input.value = '';
      return;
    }
    if (fichier.size > CV_MAX_OCTETS) {
      this.cvErreur = `Fichier trop volumineux : ${(fichier.size / 1048576).toFixed(1)} Mo pour un maximum de 5 Mo.`;
      input.value = '';
      return;
    }

    this.cvEnvoi = true;
    this.recruitment.uploadMyCv(fichier).subscribe({
      next: (cv) => {
        this.cv = cv;
        this.cvEnvoi = false;
        this.toast.success('CV enregistré.');
      },
      error: (err) => {
        this.cvEnvoi = false;
        this.cvErreur = err?.error?.detail || "Le CV n'a pas pu être envoyé.";
      },
    });
    input.value = '';
  }

  async supprimerCv(): Promise<void> {
    const ok = await this.confirmService.askDelete(
      'Supprimer votre CV ? Vos candidatures déjà envoyées gardent leur copie.'
    );
    if (!ok) return;
    this.recruitment.deleteMyCv().subscribe({
      next: (cv) => { this.cv = cv; this.toast.success('CV supprimé.'); },
      error: () => { this.cvErreur = "Le CV n'a pas pu être supprimé."; },
    });
  }

  /** Part du profil renseignée, sur ce que l'API enregistre : nom, téléphone, photo, CV. */
  get profileCompletion(): number {
    if (!this.user) return 0;
    let score = 0;
    if (this.user.full_name.trim()) score += 25;
    if (this.user.phone.trim()) score += 25;
    if (this.user.avatar_url) score += 20;
    if (this.cv?.has_cv) score += 30;
    return score;
  }

  changePassword(): void {
    const current = window.prompt('Mot de passe actuel :');
    if (!current) return;
    const next = window.prompt('Nouveau mot de passe (8 caractères minimum, avec majuscule, minuscule, chiffre et symbole) :');
    if (!next) return;

    this.userService.changePassword(current, next).subscribe({
      next: () => this.toast.success('Mot de passe modifié.'),
      error: err => this.toast.fromHttpError(err, "Le mot de passe n'a pas pu être modifié."),
    });
  }

  async deleteAccount(): Promise<void> {
    // Double confirmation conservée : la suppression de compte est
    // irréversible et efface les candidatures déjà déposées.
    const ok = await this.confirmService.ask({
      title: 'Supprimer votre compte ?',
      message: 'Votre compte et vos candidatures seront effacés. Impossible de revenir en arrière.',
      confirmLabel: 'Continuer',
      danger: true,
    });
    if (!ok) return;

    const okAgain = await this.confirmService.ask({
      title: 'Dernière confirmation',
      message: 'Toutes vos données seront supprimées.',
      confirmLabel: 'Supprimer mon compte',
      danger: true,
    });
    if (!okAgain) return;

    this.userService.deleteMe().subscribe({
      next: () => {
        this.toast.success('Votre compte a été supprimé.');
        this.authService.clearSession();
        this.router.navigate(['/register']);
      },
      error: err => this.toast.fromHttpError(err, "Le compte n'a pas pu être supprimé."),
    });
  }
}
