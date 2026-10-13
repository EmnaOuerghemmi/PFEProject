import { Component, EventEmitter, HostListener, Input, OnChanges, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

export interface ChoixCorrection { value: string; label: string; }

/**
 * Fenêtre d'une correction réservée à l'administrateur : un choix, un motif
 * obligatoire, une confirmation.
 *
 * Partagée par le retrait d'un contrat (page Contrats) et le statut forcé
 * d'une candidature (page Candidatures). Le motif est exigé ici comme côté
 * serveur (5 caractères au moins) : il entre au journal d'audit, et une
 * correction sans raison écrite ne s'explique plus six mois après.
 */
@Component({
  selector: 'app-correction-admin',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './correction-admin.component.html',
  styleUrls: ['./correction-admin.component.css'],
})
export class CorrectionAdminComponent implements OnChanges {
  @Input({ required: true }) titre = '';
  /** Ce que la correction va faire, dit avant de confirmer. */
  @Input() message = '';
  @Input() libelleChoix = 'Nouveau statut';
  @Input() choix: ChoixCorrection[] = [];
  @Input() choixInitial = '';
  @Input() libelleConfirmer = 'Confirmer';
  @Input() enCours = false;
  @Input() erreur = '';

  @Output() confirmer = new EventEmitter<{ choix: string; motif: string }>();
  @Output() annuler = new EventEmitter<void>();

  valeur = '';
  motif = '';

  ngOnChanges(): void {
    if (!this.valeur || !this.choix.some(c => c.value === this.valeur)) {
      this.valeur = this.choixInitial || this.choix[0]?.value || '';
    }
  }

  get valide(): boolean {
    return !!this.valeur && this.motif.trim().length >= 5 && !this.enCours;
  }

  valider(): void {
    if (this.valide) this.confirmer.emit({ choix: this.valeur, motif: this.motif.trim() });
  }

  @HostListener('document:keydown.escape')
  fermer(): void {
    if (!this.enCours) this.annuler.emit();
  }
}
