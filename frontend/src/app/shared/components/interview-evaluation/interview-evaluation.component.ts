import {
  Component, EventEmitter, HostListener, Input, OnChanges, Output,
  SimpleChanges, inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AssessmentService, CandidateEvaluation, InterviewSuggestion,
} from '../../../core/services/assessment.service';
import {
  CandidateFeedbackService, CandidateVisibilityState,
} from '../../../core/services/candidate-feedback.service';

/**
 * Saisie de l'évaluation d'entretien.
 *
 * Vit ici, et non dans un écran, parce qu'elle sert à deux endroits : la page
 * Entretiens (après le rendez-vous) et, en lecture, la relecture de
 * candidature. La dupliquer ferait diverger deux formulaires qui écrivent la
 * même note.
 *
 * Le principe qui tient tout : **la proposition du modèle ne devient jamais la
 * note**. Elle pré-remplit un champ que le RH corrige, et c'est la valeur du
 * champ — jamais celle du modèle — qui entre dans le score composite. Les deux
 * sont d'ailleurs stockées séparément côté serveur, pour qu'on puisse mesurer
 * plus tard si la suggestion valait quelque chose.
 */
const LIBELLES_CRITERES: Record<string, string> = {
  communication: 'Communication',
  technique: 'Technique',
  adequation: 'Adéquation',
  motivation: 'Motivation',
};

const LIBELLES_VOLETS: Record<string, string> = {
  cv: 'CV', test: 'Test technique', interview: 'Entretien',
};

@Component({
  selector: 'app-interview-evaluation',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './interview-evaluation.component.html',
  styleUrls: ['./interview-evaluation.component.css'],
})
export class InterviewEvaluationComponent implements OnChanges {
  private assessment = inject(AssessmentService);
  private feedback = inject(CandidateFeedbackService);

  @Input({ required: true }) applicationId!: string;
  /** Affiche le score composite sous le formulaire. */
  @Input() montrerComposite = true;

  /**
   * Présentation en fenêtre superposée.
   *
   * La coquille de modale vit ICI plutôt que chez l'appelant : ses styles
   * pèsent, et la page Entretiens dépasse déjà son budget CSS. Les garder
   * auprès du balisage qu'ils habillent évite aussi qu'un second appelant les
   * réécrive.
   */
  @Input() enModale = false;
  @Input() sousTitre = '';

  /** Fermeture demandée — croix, fond, ou touche Échap. */
  @Output() ferme = new EventEmitter<void>();

  /** Émis après validation — le parent rafraîchit sa liste. */
  @Output() evalue = new EventEmitter<CandidateEvaluation>();

  evaluation: CandidateEvaluation | null = null;
  chargement = false;

  notes = '';
  noteEntretien: number | null = null;
  suggestion: InterviewSuggestion | null = null;

  suggestionEnCours = false;
  enregistrement = false;
  message = '';
  erreur = '';

  readonly criteres = LIBELLES_CRITERES;
  readonly volets = LIBELLES_VOLETS;

  /**
   * Ce que le candidat a le droit de voir.
   *
   * Fermé par défaut, et refermable. Le RH décide candidature par candidature :
   * partager la note d'un test réussi n'engage pas à partager celle d'un test
   * raté. Tant que c'est fermé, le candidat ne voit pas la section — il ne voit
   * pas non plus qu'elle existe.
   */
  partage: CandidateVisibilityState | null = null;
  retourCandidat = '';
  enregistrementPartage = false;
  messagePartage = '';

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['applicationId'] && this.applicationId) {
      this.charger();
      this.chargerPartage();
    }
  }

  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.message = '';
    this.assessment.evaluation(this.applicationId).subscribe({
      next: (ev) => {
        this.chargement = false;
        this.evaluation = ev;
        this.notes = ev.interview_notes ?? '';
        this.noteEntretien = ev.interview_score;
        this.suggestion =
          (ev.interview_ai_suggestion as unknown as InterviewSuggestion) ?? null;
      },
      error: () => {
        this.chargement = false;
        this.erreur = "L'évaluation n'a pas pu être chargée.";
      },
    });
  }

  // ── Proposition ─────────────────────────────────────────────────────────────

  proposer(): void {
    if (this.suggestionEnCours || !this.notes.trim()) return;
    this.suggestionEnCours = true;
    this.erreur = '';
    this.message = '';
    this.assessment.suggestInterview(this.applicationId, this.notes).subscribe({
      next: (s) => {
        this.suggestionEnCours = false;
        this.suggestion = s;
        if (!s.available) {
          this.erreur = s.reason || 'Aucune proposition disponible.';
          return;
        }
        // Pré-remplissage seulement si le RH n'a pas déjà tranché : écraser sa
        // décision par celle du modèle serait exactement ce qu'on veut éviter.
        if (this.noteEntretien === null && s.overall !== null) {
          this.noteEntretien = Math.round(s.overall);
        }
        this.message = 'Proposition reçue — relisez-la et corrigez la note.';
      },
      error: (err) => {
        this.suggestionEnCours = false;
        this.erreur = err?.error?.detail || 'La proposition a échoué.';
      },
    });
  }

  /** Reprendre la note proposée : un clic explicite, jamais un défaut. */
  reprendreProposition(): void {
    if (this.suggestion?.overall != null) {
      this.noteEntretien = Math.round(this.suggestion.overall);
    }
  }

  // ── Enregistrement ──────────────────────────────────────────────────────────

  enregistrerNotes(): void {
    if (this.enregistrement) return;
    // L'API refuse des notes vides (422) : mieux vaut le dire ici que laisser
    // remonter un message technique.
    if (!this.notes.trim()) {
      this.erreur = 'Écrivez vos notes avant de les enregistrer.';
      return;
    }
    this.enregistrement = true;
    this.erreur = '';
    this.assessment.saveInterviewNotes(this.applicationId, this.notes).subscribe({
      next: (ev) => {
        this.enregistrement = false;
        this.evaluation = ev;
        this.message = 'Notes enregistrées.';
      },
      error: () => {
        this.enregistrement = false;
        this.erreur = "Les notes n'ont pas pu être enregistrées.";
      },
    });
  }

  enregistrerNote(): void {
    if (this.enregistrement) return;
    if (this.noteEntretien !== null &&
        (this.noteEntretien < 0 || this.noteEntretien > 100)) {
      this.erreur = "La note d'entretien va de 0 à 100.";
      return;
    }
    this.enregistrement = true;
    this.erreur = '';
    this.assessment.setInterviewScore(this.applicationId, this.noteEntretien, this.notes)
      .subscribe({
        next: (ev) => {
          this.enregistrement = false;
          this.evaluation = ev;
          this.message = 'Évaluation enregistrée — le score composite est à jour.';
          this.evalue.emit(ev);
        },
        error: (err) => {
          this.enregistrement = false;
          this.erreur = err?.error?.detail || "L'enregistrement a échoué.";
        },
      });
  }

  // ── Confort d'affichage ─────────────────────────────────────────────────────

  /**
   * Seuls les critères NOTÉS s'affichent, sans leur justification : un
   * critère « — » n'apporte rien au recruteur. Les justifications restent
   * enregistrées avec la proposition.
   */
  get clesCriteres(): string[] {
    const criteres = this.suggestion?.criteria ?? {};
    return Object.keys(criteres).filter(cle => criteres[cle]?.score != null);
  }

  get clesBreakdown(): string[] {
    return Object.keys(this.evaluation?.composite?.breakdown ?? {});
  }

  /** Le composite n'a de sens qu'accompagné du nombre de volets disponibles. */
  get completudeTexte(): string {
    const c = this.evaluation?.composite;
    return c ? `${c.completeness} volet(s) sur 3` : '';
  }

  // ── Ce que le candidat voit ─────────────────────────────────────────────

  chargerPartage(): void {
    this.feedback.visibility(this.applicationId).subscribe({
      next: (etat) => {
        this.partage = etat;
        this.retourCandidat = etat.candidate_feedback ?? '';
      },
      // Silencieux : un score peut ne pas exister encore. Le bloc de partage
      // ne s'affiche simplement pas, plutôt que d'annoncer une panne.
      error: () => { this.partage = null; },
    });
  }

  basculerNoteTest(): void {
    if (!this.partage) return;
    this.enregistrerPartage({ test_score_visible: !this.partage.test_score_visible });
  }

  basculerRetour(): void {
    if (!this.partage) return;
    this.enregistrerPartage({
      interview_feedback_visible: !this.partage.interview_feedback_visible,
      candidate_feedback: this.retourCandidat,
    });
  }

  enregistrerRetour(): void {
    this.enregistrerPartage({ candidate_feedback: this.retourCandidat });
  }

  private enregistrerPartage(corps: Record<string, unknown>): void {
    if (this.enregistrementPartage) return;
    this.enregistrementPartage = true;
    this.messagePartage = '';
    this.feedback.setVisibility(this.applicationId, corps).subscribe({
      next: (etat) => {
        this.enregistrementPartage = false;
        this.partage = etat;
        this.retourCandidat = etat.candidate_feedback ?? '';
        this.messagePartage = 'Partage mis à jour.';
      },
      error: () => {
        this.enregistrementPartage = false;
        this.erreur = "Le partage n'a pas pu être modifié.";
      },
    });
  }

  @HostListener('document:keydown.escape')
  surEchap(): void {
    if (this.enModale) this.ferme.emit();
  }

  get manquantsTexte(): string {
    return (this.evaluation?.composite?.missing ?? [])
      .map((cle) => LIBELLES_VOLETS[cle] || cle)
      .join(', ');
  }
}
