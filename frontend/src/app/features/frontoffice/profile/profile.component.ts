import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import { UserService } from '../../../core/services/user.service';
import { Router } from '@angular/router';
import { TwoFactorComponent } from '../../auth/two-factor/two-factor.component';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { CandidateCv, RecruitmentService } from '../../../core/services/recruitment.service';

interface UserProfile {
  email: string;
  full_name: string;
  username: string;
  phone?: string;
  location?: string;
  bio?: string;
  created_at?: string;
  is_admin?: boolean;
  is_rh_manager?: boolean;
  is_verified?: boolean;
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
  successMsg = '';
  errorMsg = '';
  originalUser: UserProfile | null = null;

  // ── CV de référence ────────────────────────────────────────────────────────
  // Déposé une fois, réutilisé à chaque candidature. Facultatif : un compte
  // sans CV reste parfaitement utilisable, la modale de candidature permettant
  // d'en joindre un à ce moment-là.
  private recruitment = inject(RecruitmentService);
  cv: CandidateCv | null = null;
  cvChargement = true;
  cvEnvoi = false;
  cvErreur = '';

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
        phone: '',
        location: '',
        bio: '',
        created_at: currentUser.created_at
      };
      this.originalUser = JSON.parse(JSON.stringify(this.user));
      this.userInitial = (currentUser.full_name || currentUser.email).charAt(0).toUpperCase();
    } else {
      this.router.navigate(['/login']);
    }
  }

  saveProfile() {
    if (!this.user) return;

    this.userService.updateMe({
      full_name: this.user.full_name,
      phone_number: this.user.phone,
    } as any).subscribe({
      next: () => {
        this.successMsg = 'Profil mis à jour avec succès!';
        this.errorMsg = '';
        this.originalUser = JSON.parse(JSON.stringify(this.user));
        setTimeout(() => (this.successMsg = ''), 3000);
      },
      error: err => {
        this.errorMsg = err.error?.detail || 'Échec de la mise à jour du profil.';
        this.successMsg = '';
      },
    });
  }

  chargerCv(): void {
    this.cvChargement = true;
    this.cvErreur = '';
    this.recruitment.getMyCv().subscribe({
      next: (cv) => { this.cv = cv; this.cvChargement = false; },
      error: (err) => {
        // Un échec ne doit pas se déguiser en « aucun CV » : le candidat
        // croirait devoir en redéposer un alors que le sien est peut-être
        // bien là, l'API simplement injoignable.
        this.cvChargement = false;
        this.cv = null;
        this.cvErreur = err?.status === 0
          ? 'Serveur injoignable — impossible de vérifier votre CV.'
          : "Impossible de récupérer votre CV pour l'instant.";
      },
    });
  }

  surCvChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    const fichier = input.files?.[0];
    this.cvErreur = '';
    if (!fichier) return;

    const extension = fichier.name.slice(fichier.name.lastIndexOf('.')).toLowerCase();
    if (!['.pdf', '.doc', '.docx'].includes(extension)) {
      this.cvErreur = 'Format non accepté. Déposez un PDF ou un document Word.';
      input.value = '';
      return;
    }
    if (fichier.size > 5 * 1024 * 1024) {
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
        this.cvErreur = err?.error?.detail || "L'envoi du CV a échoué.";
      },
    });
    input.value = '';
  }

  async supprimerCv(): Promise<void> {
    const ok = await this.confirmService.askDelete(
      'Supprimer votre CV ? Vos candidatures déjà envoyées conservent le leur.'
    );
    if (!ok) return;
    this.recruitment.deleteMyCv().subscribe({
      next: (cv) => { this.cv = cv; this.toast.success('CV supprimé.'); },
      error: () => { this.cvErreur = 'La suppression a échoué.'; },
    });
  }

  resetForm() {
    if (this.originalUser) {
      this.user = JSON.parse(JSON.stringify(this.originalUser));
    }
    this.successMsg = '';
    this.errorMsg = '';
  }

  changePassword() {
    const current = window.prompt('Mot de passe actuel :');
    if (!current) return;
    const next = window.prompt('Nouveau mot de passe (8+ caractères, maj/min/chiffre/spécial) :');
    if (!next) return;

    this.userService.changePassword(current, next).subscribe({
      next: () => {
        this.successMsg = 'Mot de passe modifié avec succès.';
        this.errorMsg = '';
        setTimeout(() => (this.successMsg = ''), 3000);
      },
      error: err => {
        this.errorMsg = err.error?.detail || 'Échec du changement de mot de passe.';
        this.successMsg = '';
      },
    });
  }

  async deleteAccount() {
    // Double confirmation conservée : la suppression de compte est
    // irréversible et efface les candidatures déjà déposées.
    const ok = await this.confirmService.ask({
      title: 'Supprimer votre compte',
      message: 'Cette action est définitive et ne peut pas être annulée.',
      confirmLabel: 'Continuer',
      danger: true,
    });
    if (!ok) return;

    const okAgain = await this.confirmService.ask({
      title: 'Confirmer définitivement',
      message: 'Toutes vos données, y compris vos candidatures, seront supprimées.',
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
      error: err => this.toast.fromHttpError(err, 'La suppression du compte a échoué.'),
    });
  }
}
