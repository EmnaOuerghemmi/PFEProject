import { Component, Input, OnChanges, SimpleChanges, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AssessmentService, DIFFICULTY_LABELS, QuestionDifficulty, QuestionKind,
  QuestionStatus, TestQuestion,
} from '../../../core/services/assessment.service';

/**
 * Vivier de questions d'une offre — génération, relecture, activation.
 *
 * Le cycle de vie tient en une phrase : **rien n'atteint un candidat sans
 * qu'un humain l'ait relu**. Une question sort du modèle en `GENEREE`, passe
 * `VALIDEE` d'un clic du RH, et n'est tirable qu'une fois `ACTIVE`. L'écran
 * rend ce cycle littéral — c'est sa seule raison d'être.
 *
 * Il montre donc la bonne réponse en clair : la page est réservée au RH par
 * le garde `_RH` côté API, et relire une question sans voir sa correction
 * n'aurait aucun sens.
 */
type Filtre = 'TOUTES' | QuestionStatus;

@Component({
  selector: 'app-question-bank',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './question-bank.component.html',
  styleUrls: ['./question-bank.component.css'],
})
export class QuestionBankComponent implements OnChanges {
  private assessment = inject(AssessmentService);

  /** Offre dont on gère le vivier. */
  @Input({ required: true }) jobId!: string;
  @Input() jobTitle = '';
  @Input() requiredSkills: string[] = [];

  questions: TestQuestion[] = [];
  filtre: Filtre = 'TOUTES';

  chargement = false;
  generation = false;
  activation = false;
  erreur = '';
  message = '';

  /** Édition : la question en cours de modification, ou `null`. */
  edition: TestQuestion | null = null;
  brouillon = {
    statement: '', options: '', correct: '', explanation: '',
    difficulty: 'MOYENNE' as QuestionDifficulty, skill_tag: '',
    kind: 'QCM_UNIQUE' as QuestionKind,
  };
  enregistrement = false;
  erreurEdition = '';

  readonly labels = DIFFICULTY_LABELS;
  readonly filtres: { valeur: Filtre; libelle: string }[] = [
    { valeur: 'TOUTES',  libelle: 'Toutes' },
    { valeur: 'GENEREE', libelle: 'À relire' },
    { valeur: 'VALIDEE', libelle: 'Validées' },
    { valeur: 'ACTIVE',  libelle: 'Actives' },
    { valeur: 'RETIREE', libelle: 'Retirées' },
  ];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['jobId'] && this.jobId) {
      this.filtre = 'TOUTES';
      this.charger();
    }
  }

  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.assessment.listQuestions(this.jobId).subscribe({
      next: (qs) => { this.questions = qs; this.chargement = false; },
      error: () => {
        this.chargement = false;
        this.erreur = 'Le vivier n\'a pas pu être chargé.';
      },
    });
  }

  // ── Compteurs ───────────────────────────────────────────────────────────────

  compte(statut: Filtre): number {
    return statut === 'TOUTES'
      ? this.questions.length
      : this.questions.filter((q) => q.status === statut).length;
  }

  get visibles(): TestQuestion[] {
    return this.filtre === 'TOUTES'
      ? this.questions
      : this.questions.filter((q) => q.status === this.filtre);
  }

  /** Compétences de l'offre qu'aucune question ACTIVE ne couvre encore. */
  get competencesDecouvertes(): string[] {
    const couvertes = new Set(
      this.questions
        .filter((q) => q.status === 'ACTIVE' && q.skill_tag)
        .map((q) => q.skill_tag!.toLowerCase()),
    );
    return this.requiredSkills.filter((s) => !couvertes.has(s.toLowerCase()));
  }

  get aRelire(): number { return this.compte('GENEREE'); }
  get validees(): number { return this.compte('VALIDEE'); }
  get actives(): number { return this.compte('ACTIVE'); }

  /** Sous 12 actives, aucun test complet ne peut être constitué. */
  get vivierSuffisant(): boolean { return this.actives >= 12; }

  // ── Actions de masse ────────────────────────────────────────────────────────

  generer(): void {
    if (this.generation) return;
    this.generation = true;
    this.erreur = '';
    this.message = '';
    this.assessment.generateBank(this.jobId, 30).subscribe({
      next: (rapport) => {
        this.generation = false;
        this.message = rapport.generated > 0
          ? `${rapport.generated} question(s) ajoutée(s) au vivier` +
            (rapport.rejected ? `, ${rapport.rejected} écartée(s) à la relecture automatique.` : '.')
          : 'Aucune question produite. ' + (rapport.reasons[0] || '');
        this.charger();
      },
      error: (err) => {
        this.generation = false;
        this.erreur = err?.error?.detail || 'La génération a échoué.';
      },
    });
  }

  activerTout(): void {
    if (this.activation || !this.validees) return;
    this.activation = true;
    this.assessment.activateBank(this.jobId).subscribe({
      next: (res) => {
        this.activation = false;
        this.message = `${res.activated} question(s) mise(s) en service.`;
        this.charger();
      },
      error: () => {
        this.activation = false;
        this.erreur = 'L\'activation a échoué.';
      },
    });
  }

  // ── Actions par question ────────────────────────────────────────────────────

  changerStatut(question: TestQuestion, statut: QuestionStatus): void {
    this.assessment.setQuestionStatus(question.id, statut).subscribe({
      next: (maj) => {
        const i = this.questions.findIndex((q) => q.id === maj.id);
        if (i >= 0) this.questions[i] = maj;
      },
      error: (err) => {
        this.erreur = err?.error?.detail || 'Le changement de statut a échoué.';
      },
    });
  }

  // ── Édition ─────────────────────────────────────────────────────────────────

  ouvrirEdition(question: TestQuestion | null): void {
    this.erreurEdition = '';
    this.edition = question ?? ({ id: '' } as TestQuestion);
    this.brouillon = {
      statement: question?.statement ?? '',
      options: (question?.options ?? []).join('\n'),
      correct: (question?.correct_answer ?? []).join('\n'),
      explanation: question?.explanation ?? '',
      difficulty: question?.difficulty ?? 'MOYENNE',
      skill_tag: question?.skill_tag ?? '',
      kind: question?.kind ?? 'QCM_UNIQUE',
    };
  }

  fermerEdition(): void { this.edition = null; }

  private lignes(texte: string): string[] {
    return texte.split('\n').map((l) => l.trim()).filter(Boolean);
  }

  enregistrer(): void {
    if (this.enregistrement || !this.edition) return;

    const options = this.lignes(this.brouillon.options);
    const correct = this.lignes(this.brouillon.correct);

    // Le contrôle qui compte : une bonne réponse absente des propositions
    // pénalise silencieusement un candidat compétent.
    if (this.brouillon.statement.trim().length < 10) {
      this.erreurEdition = 'L\'énoncé est trop court.'; return;
    }
    if (!correct.length) {
      this.erreurEdition = 'Indiquez au moins une bonne réponse.'; return;
    }
    if (this.brouillon.kind !== 'REPONSE_COURTE') {
      if (options.length < 2) {
        this.erreurEdition = 'Il faut au moins deux propositions.'; return;
      }
      const absentes = correct.filter((c) => !options.includes(c));
      if (absentes.length) {
        this.erreurEdition = `Bonne réponse absente des propositions : « ${absentes[0]} ».`;
        return;
      }
    }

    const corps = {
      statement: this.brouillon.statement.trim(),
      options,
      correct_answer: correct,
      explanation: this.brouillon.explanation.trim() || null,
      difficulty: this.brouillon.difficulty,
      kind: this.brouillon.kind,
      skill_tag: this.brouillon.skill_tag.trim().toLowerCase() || null,
    } as Partial<TestQuestion>;

    this.enregistrement = true;
    this.erreurEdition = '';
    const creation = !this.edition.id;
    const appel = creation
      ? this.assessment.createQuestion(this.jobId, corps)
      : this.assessment.updateQuestion(this.edition.id, corps);

    appel.subscribe({
      next: (maj) => {
        this.enregistrement = false;
        if (creation) {
          this.questions = [maj, ...this.questions];
        } else {
          const i = this.questions.findIndex((q) => q.id === maj.id);
          if (i >= 0) this.questions[i] = maj;
        }
        this.edition = null;
        this.message = creation ? 'Question ajoutée au vivier.' : 'Question mise à jour.';
      },
      error: (err) => {
        this.enregistrement = false;
        this.erreurEdition = err?.error?.detail || 'L\'enregistrement a échoué.';
      },
    });
  }

  // ── Confort d'affichage ─────────────────────────────────────────────────────

  estBonne(question: TestQuestion, option: string): boolean {
    return question.correct_answer.includes(option);
  }

  origine(question: TestQuestion): string {
    if (!question.generated_by) return 'Saisie manuelle';
    return question.generated_by.startsWith('llm:')
      ? `Générée (${question.generated_by.slice(4)})`
      : question.generated_by;
  }

  suivre(_: number, question: TestQuestion): string { return question.id; }
}
