import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AssessmentService, DIFFICULTY_LABELS, QuestionDifficulty, TestQuestion,
} from '../../../core/services/assessment.service';

/**
 * Préparation et envoi du test — l'écran « 30 → 12 ».
 *
 * Le serveur propose douze questions ; le RH décide. Toute la valeur de
 * l'écran tient dans ce qu'il montre pendant qu'il décide : la répartition
 * par difficulté face au gabarit, et les compétences de l'offre qu'aucune
 * question retenue ne couvre. Sans ces deux compteurs, un tirage plausible
 * donne douze questions sur une seule technologie et le test ne mesure plus
 * le poste.
 *
 * Les compteurs sont recalculés **ici**, à chaque clic : ceux du serveur ne
 * décrivent que sa proposition initiale et deviendraient faux dès la première
 * modification.
 */
const GABARIT: Record<QuestionDifficulty, number> = { FACILE: 4, MOYENNE: 5, DIFFICILE: 3 };

@Component({
  selector: 'app-test-dispatch',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './test-dispatch.component.html',
  styleUrls: ['./test-dispatch.component.css'],
})
export class TestDispatchComponent implements OnChanges {
  private assessment = inject(AssessmentService);

  @Input({ required: true }) applicationId!: string;
  @Input({ required: true }) jobId!: string;
  @Input() candidateName = '';
  @Input() requiredSkills: string[] = [];

  /** Émis après l'envoi : le parent rafraîchit la candidature. */
  @Output() envoye = new EventEmitter<void>();

  /** Le vivier ACTIF complet — c'est le pool dans lequel le RH pioche. */
  vivier: TestQuestion[] = [];
  /** Identifiants retenus, dans l'ordre où ils partiront. */
  retenues = new Set<string>();

  dureeMinutes = 20;
  chargement = false;
  envoi = false;
  erreur = '';

  readonly labels = DIFFICULTY_LABELS;
  readonly difficultes: QuestionDifficulty[] = ['FACILE', 'MOYENNE', 'DIFFICILE'];
  readonly gabarit = GABARIT;

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['applicationId'] || changes['jobId']) && this.applicationId && this.jobId) {
      this.charger();
    }
  }

  /**
   * Deux appels, pas un : la proposition du serveur donne la sélection de
   * départ, le vivier complet donne de quoi la modifier.
   */
  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.retenues = new Set();

    this.assessment.listQuestions(this.jobId, 'ACTIVE').subscribe({
      next: (actives) => {
        this.vivier = actives;
        this.assessment.prepareTest(this.applicationId, 12).subscribe({
          next: (prep) => {
            this.chargement = false;
            this.retenues = new Set(prep.questions.map((q) => q.id));
          },
          error: () => {
            this.chargement = false;
            this.erreur = 'La présélection a échoué — choisissez les questions à la main.';
          },
        });
      },
      error: () => {
        this.chargement = false;
        this.erreur = 'Le vivier n\'a pas pu être chargé.';
      },
    });
  }

  // ── Sélection ───────────────────────────────────────────────────────────────

  basculer(question: TestQuestion): void {
    this.retenues.has(question.id)
      ? this.retenues.delete(question.id)
      : this.retenues.add(question.id);
  }

  estRetenue(question: TestQuestion): boolean { return this.retenues.has(question.id); }

  reproposer(): void {
    this.assessment.prepareTest(this.applicationId, 12).subscribe({
      next: (prep) => { this.retenues = new Set(prep.questions.map((q) => q.id)); },
      error: () => { this.erreur = 'La présélection a échoué.'; },
    });
  }

  toutRetirer(): void { this.retenues = new Set(); }

  // ── Compteurs, recalculés à chaque clic ─────────────────────────────────────

  get selection(): TestQuestion[] {
    return this.vivier.filter((q) => this.retenues.has(q.id));
  }

  get total(): number { return this.retenues.size; }

  compteDifficulte(niveau: QuestionDifficulty): number {
    return this.selection.filter((q) => q.difficulty === niveau).length;
  }

  /** Compétences de l'offre qu'aucune question retenue ne couvre. */
  get competencesManquantes(): string[] {
    const couvertes = new Set(
      this.selection.filter((q) => q.skill_tag).map((q) => q.skill_tag!.toLowerCase()),
    );
    return this.requiredSkills.filter((s) => !couvertes.has(s.toLowerCase()));
  }

  get competencesCouvertes(): string[] {
    const couvertes = new Set(
      this.selection.filter((q) => q.skill_tag).map((q) => q.skill_tag!.toLowerCase()),
    );
    return this.requiredSkills.filter((s) => couvertes.has(s.toLowerCase()));
  }

  /** Temps que les questions retenues demandent réellement, en minutes. */
  get dureeConseillee(): number {
    const secondes = this.selection.reduce((n, q) => n + q.expected_seconds, 0);
    return Math.max(5, Math.ceil(secondes / 60));
  }

  /** Signalé, jamais bloquant : c'est au RH de trancher. */
  get dureeTropCourte(): boolean {
    return this.total > 0 && this.dureeMinutes < this.dureeConseillee;
  }

  get peutEnvoyer(): boolean { return this.total > 0 && !this.envoi; }

  // ── Envoi ───────────────────────────────────────────────────────────────────

  envoyer(): void {
    if (!this.peutEnvoyer) return;
    this.envoi = true;
    this.erreur = '';
    // L'ordre d'affichage du vivier fixe l'ordre d'envoi ; le serveur mélange
    // ensuite, donc il n'a pas à être significatif ici.
    const ids = this.selection.map((q) => q.id);
    this.assessment.sendTest(this.applicationId, ids, this.dureeMinutes).subscribe({
      next: () => { this.envoi = false; this.envoye.emit(); },
      error: (err) => {
        this.envoi = false;
        this.erreur = err?.error?.detail || 'L\'envoi a échoué.';
      },
    });
  }

  suivre(_: number, question: TestQuestion): string { return question.id; }
}
