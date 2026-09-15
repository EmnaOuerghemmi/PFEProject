import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import * as QRCode from 'qrcode';

import { AuthService, TotpSetup } from '../../../core/services/auth.service';

/**
 * Gestion de la double authentification (TOTP).
 *
 * Trois états possibles :
 *   - `idle`     : 2FA inactive, proposition de l'activer
 *   - `setup`    : QR code affiché, en attente du code de confirmation
 *   - `enabled`  : 2FA active, possibilité de la désactiver
 *
 * Point d'attention : les codes de secours ne sont renvoyés qu'à l'appel de
 * `setup`, en clair et une seule fois. Ils restent donc affichés tant que
 * l'utilisateur n'a pas explicitement confirmé les avoir conservés — les
 * masquer plus tôt les rendrait définitivement irrécupérables.
 */
@Component({
  selector: 'app-two-factor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './two-factor.component.html',
  styleUrls: ['./two-factor.component.css'],
})
export class TwoFactorComponent implements OnInit {
  private auth = inject(AuthService);

  readonly state = signal<'idle' | 'setup' | 'enabled'>('idle');
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly success = signal<string | null>(null);

  readonly qrDataUrl = signal<string | null>(null);
  readonly setupData = signal<TotpSetup | null>(null);
  /** Tant que faux, on conserve les codes de secours à l'écran. */
  readonly backupCodesAcknowledged = signal(false);

  confirmCode = '';
  disableCode = '';

  ngOnInit(): void {
    // `totp_enabled` est porté par le profil utilisateur renvoyé par /users/me.
    const user = this.auth.getCurrentUser() as ({ totp_enabled?: boolean } | null);
    this.state.set(user?.totp_enabled ? 'enabled' : 'idle');
  }

  /**
   * Prépare (ou réinitialise) la double authentification.
   *
   * Quand elle est déjà active, le serveur exige un code valide avant de
   * remplacer le secret : sans cette preuve de possession, un jeton d'accès
   * volé permettrait de casser l'authenticator du titulaire et de repartir
   * avec un jeu de codes de secours neuf. On réutilise ici le champ de saisie
   * déjà présent dans le bloc « activée ».
   */
  startSetup(): void {
    const currentCode = this.state() === 'enabled' ? this.disableCode.trim() : undefined;
    if (this.state() === 'enabled' && (!currentCode || currentCode.length < 6)) {
      this.error.set('Saisissez un code valide pour réinitialiser la double authentification.');
      return;
    }

    this.loading.set(true);
    this.error.set(null);
    this.success.set(null);
    this.auth.setup2fa(currentCode).subscribe({
      next: async (data) => {
        this.setupData.set(data);
        this.backupCodesAcknowledged.set(false);
        try {
          // Le QR encode l'URI otpauth:// : l'application d'authentification
          // y lit l'émetteur, le compte et le secret d'un seul coup.
          this.qrDataUrl.set(
            await QRCode.toDataURL(data.provisioning_uri, { width: 220, margin: 1 })
          );
        } catch {
          // Sans QR, la saisie manuelle du secret reste possible : on n'échoue
          // pas l'activation pour autant.
          this.qrDataUrl.set(null);
        }
        this.state.set('setup');
        this.disableCode = '';
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? "Impossible d'initialiser la double authentification.");
        this.loading.set(false);
      },
    });
  }

  confirmEnable(): void {
    if (this.confirmCode.trim().length < 6) {
      this.error.set('Saisissez le code à 6 chiffres affiché par votre application.');
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.auth.enable2fa(this.confirmCode.trim()).subscribe({
      next: () => {
        this.state.set('enabled');
        this.success.set('Double authentification activée.');
        this.confirmCode = '';
        this.qrDataUrl.set(null);
        this.setupData.set(null);
        this.loading.set(false);
        this.auth.loadCurrentUser().subscribe();
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Code invalide. Vérifiez l\'heure de votre téléphone.');
        this.loading.set(false);
      },
    });
  }

  cancelSetup(): void {
    // Retour à « inactive » et non à « activée », même après une
    // reconfiguration : le serveur a suspendu la protection en remplaçant le
    // secret, elle ne redeviendra active qu'après confirmation du nouveau code.
    this.state.set('idle');
    this.qrDataUrl.set(null);
    this.setupData.set(null);
    this.confirmCode = '';
    this.error.set(null);
    this.auth.loadCurrentUser().subscribe();
  }

  disable(): void {
    if (this.disableCode.trim().length < 6) {
      this.error.set('Saisissez un code valide pour confirmer la désactivation.');
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.auth.disable2fa(this.disableCode.trim()).subscribe({
      next: () => {
        this.state.set('idle');
        this.success.set('Double authentification désactivée.');
        this.disableCode = '';
        this.loading.set(false);
        this.auth.loadCurrentUser().subscribe();
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Code invalide.');
        this.loading.set(false);
      },
    });
  }

  copyBackupCodes(): void {
    const codes = this.setupData()?.backup_codes;
    if (!codes) return;
    navigator.clipboard?.writeText(codes.join('\n'));
    this.success.set('Codes copiés dans le presse-papiers.');
  }

  /** Restreint la saisie aux chiffres — les codes TOTP sont numériques. */
  onlyDigits(event: Event): void {
    const input = event.target as HTMLInputElement;
    input.value = input.value.replace(/\D/g, '').slice(0, 6);
  }
}
