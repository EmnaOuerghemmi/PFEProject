import { Component, HostListener, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { PasswordService } from '../../../core/services/password.service';
import { RoleRedirectService } from '../../../core/services/role-redirect.service';
import { RecruitmentService } from '../../../core/services/recruitment.service';
import { ToastService } from '../../../core/services/toast.service';

/**
 * Inscription en deux temps, sur un seul écran.
 *
 * Le formulaire cède la place à la saisie du code reçu par e-mail sans
 * changement de route : l'utilisateur garde son contexte visuel, et l'adresse
 * ainsi que le mot de passe qu'il vient de choisir restent en mémoire — plus
 * besoin de les faire transiter par l'URL vers une seconde page.
 *
 * La page autonome /verify-email subsiste comme porte de secours pour qui
 * ferme l'onglet avant d'avoir saisi son code.
 */
@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './register.component.html',
  styleUrls: ['./register.component.css']
})
export class RegisterComponent {
  /** Longueur du code — doit suivre EMAIL_OTP_LENGTH côté backend. */
  readonly codeLength = 6;

  /** Étape courante : saisie des informations, puis saisie du code. */
  step: 'form' | 'verify' = 'form';

  /**
   * CV choisi pendant l'inscription — FACULTATIF.
   *
   * Il n'est pas envoyé avec le formulaire : l'inscription reçoit du JSON et
   * le compte n'est authentifié qu'après la saisie du code reçu par e-mail.
   * Le fichier est donc gardé côté client puis déposé juste après la
   * vérification, quand le jeton existe. Pour le candidat, c'est transparent :
   * il choisit son CV à l'inscription, il le retrouve dans son profil.
   *
   * Le document est en revanche VÉRIFIÉ dès qu'il est choisi (le serveur dit
   * si c'est un CV, sans l'enregistrer) : un refus doit arrêter l'inscription
   * ici, pas une fois le compte créé.
   */
  cvFile: File | null = null;
  cvErreur = '';
  /** Vérification du document choisi en cours. */
  cvVerification = false;
  /** Nom du document refusé : l'inscription attend qu'il soit retiré ou remplacé. */
  cvRefuse: string | null = null;

  firstName: string = '';
  lastName: string = '';
  username: string = '';
  email: string = '';
  password: string = '';
  confirmPassword: string = '';
  showPassword: boolean = false;
  showConfirm: boolean = false;
  isLoading: boolean = false;
  errorMessage: string = '';
  currentYear: number = new Date().getFullYear();

  /** Étape de vérification. */
  code: string = '';
  isResending: boolean = false;
  infoMessage: string = '';

  leftEyeStyle = { transform: 'translate(0px, 0px)' };
  rightEyeStyle = { transform: 'translate(0px, 0px)' };

  @ViewChild('leftEye') leftEyeRef!: ElementRef;
  @ViewChild('rightEye') rightEyeRef!: ElementRef;

  constructor(
    private authService: AuthService,
    private passwordService: PasswordService,
    private roleRedirectService: RoleRedirectService,
    private recruitmentService: RecruitmentService,
    private router: Router,
    private toast: ToastService,
  ) {}

  @HostListener('document:mousemove', ['$event'])
  onMouseMove(event: MouseEvent): void {
    this.moveEye(this.leftEyeRef, event, this.leftEyeStyle);
    this.moveEye(this.rightEyeRef, event, this.rightEyeStyle);
  }

  private moveEye(eyeRef: ElementRef, event: MouseEvent, styleObj: any): void {
    if (!eyeRef?.nativeElement) return;
    const rect = eyeRef.nativeElement.getBoundingClientRect();
    const dx = event.clientX - (rect.left + rect.width / 2);
    const dy = event.clientY - (rect.top + rect.height / 2);
    const dist = Math.min(Math.hypot(dx, dy), 6);
    const angle = Math.atan2(dy, dx);
    styleObj.transform = `translate(${Math.cos(angle) * dist}px, ${Math.sin(angle) * dist}px)`;
  }

  register(): void {
    if (!this.firstName || !this.lastName || !this.username || !this.email || !this.password) {
      this.errorMessage = 'Veuillez remplir tous les champs.';
      return;
    }
    if (this.password !== this.confirmPassword) {
      this.errorMessage = 'Les mots de passe ne correspondent pas.';
      return;
    }
    if (!this.isPasswordValid(this.password)) {
      this.errorMessage = 'Le mot de passe doit contenir au moins 8 caractères avec une majuscule, une minuscule, un chiffre et un caractère spécial.';
      return;
    }
    if (this.cvVerification) return;
    if (this.cvRefuse) {
      this.errorMessage = "Le document joint n'est pas accepté comme CV. "
        + 'Joignez votre CV, ou retirez ce document pour vous inscrire sans CV.';
      return;
    }
    this.isLoading = true;
    this.errorMessage = '';
    // Aucun `role` n'est transmis : le serveur impose READ_ONLY à l'inscription
    // publique et ignorerait de toute façon un rôle envoyé par le client.
    this.authService.register({
      email: this.email,
      username: this.username,
      password: this.password,
      full_name: `${this.firstName} ${this.lastName}`.trim()
    }).subscribe({
      next: () => {
        this.isLoading = false;
        // Le compte existe mais n'est pas encore vérifié : on bascule l'écran
        // sur la saisie du code, sans navigation.
        this.step = 'verify';
        this.errorMessage = '';
        this.infoMessage = '';
        this.code = '';
      },
      error: (err: any) => {
        this.isLoading = false;
        this.errorMessage = err?.error?.detail || err?.error?.message || 'Échec de l\'inscription. Veuillez réessayer.';
      }
    });
  }

  // ── Étape 2 : vérification de l'adresse ────────────────────────────────

  get canVerify(): boolean {
    return !this.isLoading && this.code.length === this.codeLength;
  }

  /** Le code est numérique : on filtre la saisie et les collages. */
  onCodeInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    input.value = input.value.replace(/\D/g, '').slice(0, this.codeLength);
    this.code = input.value;
  }

  verifyCode(): void {
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
        if (!response?.access_token) {
          this.router.navigate(['/login']);
          return;
        }
        this.authService.setToken(response.access_token);
        if (response.refresh_token) {
          this.authService.setRefreshToken(response.refresh_token);
        }
        // Charger le profil AVANT de rediriger : c'est le rôle qui décide de
        // la destination (accueil candidat, ou backoffice).
        this.authService.loadCurrentUser().subscribe({
          next: () => this.deposerCvPuisRediriger(),
          error: () => this.router.navigate(['/login']),
        });
      },
      error: (err: any) => {
        this.isLoading = false;
        this.code = '';
        this.errorMessage =
          err?.error?.detail || err?.error?.message || 'Code invalide. Veuillez réessayer.';
      }
    });
  }

  resendCode(): void {
    this.isResending = true;
    this.errorMessage = '';
    this.infoMessage = '';

    this.passwordService.resendVerificationCode(this.email).subscribe({
      next: () => {
        this.isResending = false;
        this.code = '';
        this.infoMessage = 'Un nouveau code vient d\'être envoyé. Vérifiez votre boîte de réception.';
      },
      error: (err: any) => {
        this.isResending = false;
        this.errorMessage =
          err?.error?.detail || 'Envoi impossible pour le moment. Réessayez dans quelques minutes.';
      }
    });
  }

  /**
   * Retour au formulaire pour corriger une adresse mal saisie.
   *
   * Le compte a déjà été créé sous l'ancienne adresse : on repart donc d'un
   * formulaire vierge côté identifiants, sinon une nouvelle soumission
   * échouerait sur « adresse déjà enregistrée » sans que ce soit clair.
   */
  /** Sélection du CV à l'inscription : validée ici, déposée après l'OTP. */
  surCvChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    const fichier = input.files?.[0] ?? null;
    this.cvErreur = '';
    this.cvRefuse = null;
    if (!fichier) { this.cvFile = null; return; }

    const extension = fichier.name.slice(fichier.name.lastIndexOf('.')).toLowerCase();
    if (!['.pdf', '.docx'].includes(extension)) {
      this.cvErreur = 'Format non accepté. Déposez un PDF ou un document Word (.docx).';
      this.cvFile = null; input.value = ''; return;
    }
    if (fichier.size > 5 * 1024 * 1024) {
      this.cvErreur = `Fichier trop volumineux : ${(fichier.size / 1048576).toFixed(1)} Mo pour un maximum de 5 Mo.`;
      this.cvFile = null; input.value = ''; return;
    }

    this.cvFile = null;
    this.cvVerification = true;
    this.recruitmentService.verifierCv(fichier).subscribe({
      next: () => {
        this.cvVerification = false;
        this.cvFile = fichier;
      },
      error: (err: any) => {
        this.cvVerification = false;
        input.value = '';
        if (err?.status === 400 && typeof err.error?.detail === 'string') {
          // Pas un CV, texte illisible, ou fichier invalide.
          this.cvErreur = err.error.detail;
          this.cvRefuse = fichier.name;
          return;
        }
        // Vérification indisponible (réseau, quota atteint) : le fichier est
        // gardé, son dépôt après l'inscription le vérifie de toute façon.
        this.cvFile = fichier;
      },
    });
  }

  retirerCv(): void {
    this.cvFile = null;
    this.cvErreur = '';
    this.cvRefuse = null;
  }

  /**
   * Dépose le CV choisi à l'inscription, puis redirige.
   *
   * Un échec ici ne bloque JAMAIS l'entrée : le compte est créé et vérifié,
   * le CV reste facultatif. Mais le candidat doit savoir que son CV n'est PAS
   * enregistré — sinon il postule en croyant le retrouver dans son profil.
   * On l'amène donc au profil, là où il peut en déposer un autre.
   */
  private deposerCvPuisRediriger(): void {
    if (!this.cvFile) {
      this.roleRedirectService.redirectBasedOnRole();
      return;
    }
    this.recruitmentService.uploadMyCv(this.cvFile).subscribe({
      next: () => this.roleRedirectService.redirectBasedOnRole(),
      error: (err: any) => {
        // Une 400 (document refusé par le détecteur de CV, illisible, ou
        // fichier invalide) n'est pas notifiée par l'intercepteur, qui la
        // laisse aux formulaires : ici, plus de formulaire pour l'afficher.
        // Les autres échecs ont déjà leur toast.
        if (err?.status === 400 && typeof err.error?.detail === 'string') {
          this.toast.error(err.error.detail, 'CV non enregistré');
        }
        this.router.navigate(['/frontoffice/profile']);
      },
    });
  }

  backToForm(): void {
    this.step = 'form';
    this.code = '';
    this.errorMessage = '';
    this.infoMessage = '';
    this.email = '';
    this.username = '';
    this.password = '';
    this.confirmPassword = '';
  }

  isPasswordValid(p: string): boolean {
    return /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{};':"\\|,.<>/?]).{8,}$/.test(p);
  }

  get passwordStrength(): number {
    const p = this.password;
    if (!p) return 0;
    let score = 0;
    if (p.length >= 8) score++;
    if (p.length >= 12) score++;
    if (/[A-Z]/.test(p)) score++;
    if (/[0-9]/.test(p)) score++;
    if (/[!@#$%^&*()\-_=+\[\]{};':"\\|,.<>/?]/.test(p)) score++;
    return score;
  }

  get strengthLabel(): string {
    const s = this.passwordStrength;
    if (s <= 1) return 'Faible';
    if (s <= 3) return 'Moyen';
    return 'Fort';
  }
}
