import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, ActivatedRoute } from '@angular/router';
import { PasswordService } from '../../../core/services/password.service';
import { AuthService } from '../../../core/services/auth.service';
import { RoleRedirectService } from '../../../core/services/role-redirect.service';

/**
 * Saisie du code de vérification envoyé par e-mail après l'inscription.
 *
 * Remplace l'ancien parcours par lien cliquable : un code se recopie du
 * téléphone vers l'ordinateur, alors qu'un lien impose d'ouvrir sa messagerie
 * sur la machine où l'on s'est inscrit, et se fait régulièrement mutiler par
 * les analyseurs d'URL des clients de messagerie.
 *
 * En cas de succès, le backend renvoie directement un couple de jetons :
 * l'utilisateur est redirigé vers son accueil (le frontoffice pour un
 * candidat) sans repasser par l'écran de connexion.
 */
@Component({
  selector: 'app-verify-email',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './verify-email.component.html',
  styleUrl: './verify-email.component.css'
})
export class VerifyEmailComponent implements OnInit {
  /** Longueur attendue du code — doit suivre EMAIL_OTP_LENGTH côté backend. */
  readonly codeLength = 6;

  email: string = '';
  code: string = '';

  isLoading: boolean = false;
  isResending: boolean = false;
  isSuccess: boolean = false;
  errorMessage: string = '';
  infoMessage: string = '';
  currentYear: number = new Date().getFullYear();

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private passwordService: PasswordService,
    private authService: AuthService,
    private roleRedirectService: RoleRedirectService,
  ) {}

  ngOnInit(): void {
    // L'adresse est transmise par l'écran d'inscription. Elle reste modifiable
    // pour les arrivées directes (lien mis en favori, code demandé plus tard).
    this.route.queryParams.subscribe(params => {
      this.email = params['email'] || '';
    });
  }

  get canSubmit(): boolean {
    return !this.isLoading && !!this.email && this.code.length === this.codeLength;
  }

  /** Le code est numérique : on filtre la saisie et les collages. */
  onCodeInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    input.value = input.value.replace(/\D/g, '').slice(0, this.codeLength);
    this.code = input.value;
  }

  verify(): void {
    if (!this.email) {
      this.errorMessage = 'Renseignez l\'adresse e-mail utilisée à l\'inscription.';
      return;
    }
    if (this.code.length !== this.codeLength) {
      this.errorMessage = `Le code comporte ${this.codeLength} chiffres.`;
      return;
    }

    this.isLoading = true;
    this.errorMessage = '';
    this.infoMessage = '';

    this.passwordService.verifyEmail(this.email, this.code).subscribe({
      next: (response) => {
        this.isLoading = false;
        this.isSuccess = true;

        if (response?.access_token) {
          this.authService.setToken(response.access_token);
          if (response.refresh_token) {
            this.authService.setRefreshToken(response.refresh_token);
          }
          // Charger le profil AVANT de rediriger : c'est le rôle qui décide de
          // la destination (accueil candidat ou backoffice).
          this.authService.loadCurrentUser().subscribe({
            next: () => this.roleRedirectService.redirectBasedOnRole(),
            error: () => this.router.navigate(['/login']),
          });
        } else {
          this.router.navigate(['/login']);
        }
      },
      error: (error) => {
        this.isLoading = false;
        this.code = '';
        this.errorMessage =
          error?.error?.detail || error?.error?.message || 'Code invalide. Veuillez réessayer.';
      }
    });
  }

  resend(): void {
    if (!this.email) {
      this.errorMessage = 'Renseignez d\'abord votre adresse e-mail.';
      return;
    }
    this.isResending = true;
    this.errorMessage = '';
    this.infoMessage = '';

    this.passwordService.resendVerificationCode(this.email).subscribe({
      next: () => {
        this.isResending = false;
        this.code = '';
        this.infoMessage = 'Un nouveau code vient d\'être envoyé. Vérifiez votre boîte de réception.';
      },
      error: (error) => {
        this.isResending = false;
        this.errorMessage =
          error?.error?.detail || 'Envoi impossible pour le moment. Réessayez dans quelques minutes.';
      }
    });
  }
}
