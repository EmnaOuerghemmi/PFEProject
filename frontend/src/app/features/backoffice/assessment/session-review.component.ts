import {
  Component, EventEmitter, Input, OnChanges, Output, SimpleChanges, inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AssessmentService, AnswerReview, CandidateEvaluation, DIFFICULTY_LABELS,
  OUTCOME_LABELS, TestSessionDetail,
} from '../../../core/services/assessment.service';

/**
 * Relecture d'une candidature : résultats du test, entretien, score composite.
 *
 * Deux choses que cet écran est seul à montrer :
 *
 * 1. **Le détail par réponse** — quelle question, quelle réponse donnée,
 *    quelle bonne réponse, et de combien le temps attendu a été dépassé.
 *    Le candidat, lui, n'a jamais accès à cette page ni à ses chiffres.
 * 2. **La réussite par compétence** — c'est elle qui sert à préparer
 *    l'entretien : on interroge là où le test a montré une faiblesse.
 *
 * Le score composite est affiché ici, mais la note d'entretien se SAISIT
 * ailleurs — dans la page Entretiens, une fois le rendez-vous passé. Noter un
 * entretien depuis l'écran du test reviendrait à le noter avant de l'avoir mené.
 */
const LIBELLES_VOLETS: Record<string, string> = {
  cv: 'CV', test: 'Test technique', interview: 'Entretien',
};

@Component({
  selector: 'app-session-review',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './session-review.component.html',
  styleUrls: ['./session-review.component.css'],
})
export class SessionReviewComponent implements OnChanges {
  private assessment = inject(AssessmentService);

  @Input({ required: true }) applicationId!: string;

  /**
   * Demande d'organiser un entretien.
   *
   * L'écran ne planifie pas lui-même : la page Entretiens sait faire, et le
   * parent connaît déjà la modale de planification. Y ajouter une seconde
   * implémentation en ferait deux à maintenir.
   */
  @Output() lancerEntretien = new EventEmitter<void>();

  session: TestSessionDetail | null = null;
  /** Distingue « pas encore de test » d'une erreur de chargement. */
  aucunTest = false;
  chargementSession = false;
  erreurSession = '';

  evaluation: CandidateEvaluation | null = null;
  chargementEval = false;

  /** Réponse dépliée dans le détail, s'il y en a une. */
  ouverte: number | null = null;

  readonly diffLabels = DIFFICULTY_LABELS;
  readonly outcomeLabels = OUTCOME_LABELS;
  readonly volets = LIBELLES_VOLETS;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['applicationId'] && this.applicationId) {
      this.ouverte = null;
      this.chargerSession();
      this.chargerEvaluation();
    }
  }

  // ── Résultats du test ───────────────────────────────────────────────────────

  chargerSession(): void {
    this.chargementSession = true;
    this.aucunTest = false;
    this.erreurSession = '';
    this.session = null;
    this.assessment.sessionDetail(this.applicationId).subscribe({
      next: (detail) => { this.session = detail; this.chargementSession = false; },
      error: (err) => {
        this.chargementSession = false;
        if (err?.status === 404) { this.aucunTest = true; return; }
        this.erreurSession = 'Les résultats n\'ont pas pu être chargés.';
      },
    });
  }

  basculer(position: number): void {
    this.ouverte = this.ouverte === position ? null : position;
  }

  /** Résumé lisible d'un dépassement — « +42 s » ou « dans les temps ». */
  depassement(reponse: AnswerReview): string {
    if (!reponse.overrun_seconds) return 'dans les temps';
    return `+${reponse.overrun_seconds} s au-delà de ${reponse.expected_seconds} s`;
  }

  get depassementTotal(): string {
    if (!this.session?.total_overrun_seconds) return '';
    const s = this.session.total_overrun_seconds;
    const m = Math.floor(s / 60);
    return m ? `${m} min ${s % 60} s` : `${s} s`;
  }

  compte(issue: string): number { return this.session?.outcome_counts?.[issue] ?? 0; }

  libelleStatut(statut: string): string {
    return ({
      ENVOYE: 'Envoyé, non ouvert', EN_COURS: 'En cours', TERMINE: 'Terminé',
      EXPIRE: 'Temps écoulé', ABANDONNE: 'Lien expiré',
    } as Record<string, string>)[statut] || statut;
  }

  // ── Entretien et composite ──────────────────────────────────────────────────

  /**
   * Charge l'évaluation pour AFFICHER le composite — en lecture seule.
   *
   * La saisie, elle, a lieu dans la page Entretiens : c'est la seule qui sache
   * quand le rendez-vous a eu lieu, et noter un entretien avant de l'avoir mené
   * n'a pas de sens.
   */
  chargerEvaluation(): void {
    this.chargementEval = true;
    this.assessment.evaluation(this.applicationId).subscribe({
      next: (ev) => {
        this.chargementEval = false;
        this.evaluation = ev;
      },
      // Silencieux : le composite est un complément, pas le contenu de la page.
      // Une erreur ici ne doit pas masquer les résultats du test.
      error: () => { this.chargementEval = false; },
    });
  }

  // ── Confort d'affichage ─────────────────────────────────────────────────────

  get clesBreakdown(): string[] {
    return Object.keys(this.evaluation?.composite?.breakdown ?? {});
  }

  /** Le composite n'a de sens qu'accompagné du nombre de volets disponibles. */
  get completudeTexte(): string {
    const c = this.evaluation?.composite;
    if (!c) return '';
    return `${c.completeness} volet(s) sur 3`;
  }

  /** Les volets manquants en toutes lettres — l'API renvoie ses clés internes. */
  get manquantsTexte(): string {
    return (this.evaluation?.composite?.missing ?? [])
      .map((cle) => LIBELLES_VOLETS[cle] || cle)
      .join(', ');
  }

  suivre(_: number, reponse: AnswerReview): number { return reponse.position; }
}
