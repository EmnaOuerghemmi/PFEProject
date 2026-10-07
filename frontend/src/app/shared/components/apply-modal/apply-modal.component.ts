import { Component, EventEmitter, HostListener, Input, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { CandidateCv, JobOffer, RecruitmentService } from '../../../core/services/recruitment.service';

/**
 * Modale de candidature, en deux temps.
 *
 * 1. **Le CV** — réutiliser celui du profil, ou en déposer un autre.
 * 2. **La prétention salariale** — demandée APRÈS l'envoi, jamais avant.
 *
 * L'ordre n'est pas cosmétique : la candidature est créée dès l'étape 1. Un
 * candidat qui hésite sur un montant, ferme la fenêtre ou clique sur « Passer »
 * a déjà postulé. Poser la question d'abord ferait perdre des dossiers sur un
 * chiffre que le candidat n'a pas forcément en tête.
 */
type Etape = 'cv' | 'salaire' | 'termine';

@Component({
  selector: 'app-apply-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './apply-modal.component.html',
  styleUrls: ['./apply-modal.component.css'],
})
export class ApplyModalComponent {
  private recruitment = inject(RecruitmentService);

  @Input({ required: true }) job!: JobOffer;

  /** Émis quand la candidature est enregistrée — le parent rafraîchit son état. */
  @Output() applied = new EventEmitter<void>();
  @Output() closed = new EventEmitter<void>();

  etape: Etape = 'cv';
  chargementCv = true;
  cvProfil: CandidateCv | null = null;

  /** 'profil' = réutiliser le CV enregistré ; 'nouveau' = déposer un fichier. */
  source: 'profil' | 'nouveau' = 'nouveau';
  fichier: File | null = null;
  enregistrerDansProfil = true;

  envoi = false;
  erreur = '';

  applicationId: string | null = null;
  pretention: number | null = null;
  envoiPretention = false;

  ngOnInit(): void {
    this.recruitment.getMyCv().subscribe({
      next: (cv) => {
        this.cvProfil = cv;
        // Un CV déjà en place devient le choix par défaut : c'est le geste
        // attendu, postuler sans rien redéposer.
        this.source = cv.has_cv ? 'profil' : 'nouveau';
        this.chargementCv = false;
      },
      error: () => { this.chargementCv = false; },
    });
  }

  @HostListener('document:keydown.escape')
  surEchap(): void {
    // On ne ferme pas pendant un envoi : l'utilisateur croirait avoir annulé.
    if (!this.envoi && !this.envoiPretention) this.fermer();
  }

  surFichier(event: Event): void {
    const input = event.target as HTMLInputElement;
    const choisi = input.files?.[0] ?? null;
    this.erreur = '';
    if (!choisi) { this.fichier = null; return; }

    const extension = choisi.name.slice(choisi.name.lastIndexOf('.')).toLowerCase();
    if (!['.pdf', '.docx'].includes(extension)) {
      this.erreur = 'Format non accepté. Déposez un PDF ou un document Word (.docx).';
      this.fichier = null;
      input.value = '';
      return;
    }
    if (choisi.size > 5 * 1024 * 1024) {
      this.erreur = `Fichier trop volumineux : ${(choisi.size / 1048576).toFixed(1)} Mo pour un maximum de 5 Mo.`;
      this.fichier = null;
      input.value = '';
      return;
    }
    this.fichier = choisi;
    this.source = 'nouveau';
  }

  get peutEnvoyer(): boolean {
    if (this.envoi) return false;
    return this.source === 'profil' ? !!this.cvProfil?.has_cv : !!this.fichier;
  }

  envoyer(): void {
    if (!this.peutEnvoyer) return;
    this.envoi = true;
    this.erreur = '';

    const fichier = this.source === 'nouveau' ? this.fichier : null;
    this.recruitment.applyToJob(this.job.id, fichier, this.enregistrerDansProfil).subscribe({
      next: (application) => {
        this.envoi = false;
        this.applicationId = application.id;
        this.etape = 'salaire';
        // La candidature est enregistrée : le parent peut déjà se mettre à jour,
        // même si le candidat ne répond pas à la question suivante.
        this.applied.emit();
      },
      error: (err) => {
        this.envoi = false;
        this.erreur = this.messageErreur(err);
      },
    });
  }

  /**
   * Trois causes, trois conduites à tenir.
   *
   * « Réessayez » est un mauvais conseil pour une session expirée comme pour
   * un serveur injoignable : dans le premier cas il faut se reconnecter, dans
   * le second attendre. Les confondre fait perdre au candidat le fichier qu'il
   * vient de choisir, sans qu'il sache pourquoi.
   */
  private messageErreur(err: any): string {
    if (err?.status === 401 || err?.status === 403) {
      return 'Votre session a expiré. Reconnectez-vous, puis reprenez votre candidature.';
    }
    if (err?.status === 0) {
      return 'Serveur injoignable. Vérifiez votre connexion et réessayez.';
    }
    return err?.error?.detail || "L'envoi a échoué. Réessayez.";
  }

  /** Fourchette de l'offre, en repère pour le candidat. */
  get fourchette(): string | null {
    const { salary_min: min, salary_max: max } = this.job;
    if (min == null && max == null) return null;
    if (min != null && max != null) return `${min} – ${max} TND`;
    return `${min ?? max} TND`;
  }

  enregistrerPretention(): void {
    if (this.envoiPretention || !this.applicationId) return;
    if (this.pretention == null || this.pretention <= 0) { this.passer(); return; }

    this.envoiPretention = true;
    this.recruitment.setExpectedSalary(this.applicationId, this.pretention).subscribe({
      next: () => { this.envoiPretention = false; this.etape = 'termine'; },
      error: () => {
        // La candidature, elle, est bien enregistrée : on ne bloque pas le
        // candidat sur l'échec d'une étape facultative.
        this.envoiPretention = false;
        this.etape = 'termine';
      },
    });
  }

  passer(): void {
    this.etape = 'termine';
  }

  fermer(): void {
    this.closed.emit();
  }
}
