import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import {
  AssessmentService, PublicQuestion, PublicTestIntro,
} from '../../core/services/assessment.service';

/**
 * Passage du test technique — page publique, accessible par jeton.
 *
 * Trois règles de conception, qui tiennent toutes à l'intégrité du test :
 *
 * 1. **Aucun retour en arrière.** Le serveur ne sert que la question en cours ;
 *    l'écran n'a donc rien à mémoriser ni à ré-afficher.
 * 2. **Seul le temps GLOBAL est montré.** Un compte à rebours par question
 *    créerait une panique qui fausse précisément la mesure prise.
 * 3. **Rien sur la justesse.** Le candidat n'apprend jamais s'il a eu bon —
 *    l'apprendre question après question reviendrait à lui livrer le vivier.
 *
 * Le décompte affiché est purement cosmétique : il repart du `seconds_remaining`
 * renvoyé par le serveur à chaque réponse. C'est toujours le serveur qui
 * tranche l'expiration.
 */
type Etape = 'chargement' | 'accueil' | 'question' | 'termine' | 'erreur';

@Component({
  selector: 'app-test-run',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './test-run.component.html',
  styleUrls: ['./test-run.component.css'],
})
export class TestRunComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private assessment = inject(AssessmentService);

  etape: Etape = 'chargement';
  erreur = '';

  token = '';
  intro: PublicTestIntro | null = null;
  question: PublicQuestion | null = null;

  /** Options cochées pour la question en cours. */
  choix = new Set<string>();
  reponseCourte = '';
  envoi = false;

  secondesRestantes = 0;
  private minuteur?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') ?? '';
    if (!this.token) {
      this.etape = 'erreur';
      this.erreur = 'Lien invalide.';
      return;
    }
    this.assessment.publicIntro(this.token).subscribe({
      next: (intro) => {
        this.intro = intro;
        if (intro.already_submitted) { this.etape = 'termine'; return; }
        if (intro.link_expired) {
          this.etape = 'erreur';
          this.erreur = 'Ce lien a expiré. Contactez le recruteur pour en obtenir un nouveau.';
          return;
        }
        this.etape = 'accueil';
      },
      error: (err) => {
        this.etape = 'erreur';
        this.erreur = err?.status === 404
          ? "Ce test n'existe pas ou le lien est incomplet."
          : 'Impossible de charger le test. Réessayez dans un instant.';
      },
    });
  }

  ngOnDestroy(): void {
    this.arreterMinuteur();
  }

  demarrer(): void {
    if (this.envoi) return;
    this.envoi = true;
    this.assessment.publicStart(this.token).subscribe({
      next: (res) => {
        this.envoi = false;
        this.appliquer(res.next_question, res.finished);
      },
      error: (err) => {
        this.envoi = false;
        this.etape = 'erreur';
        this.erreur = err?.status === 410
          ? 'Ce lien a expiré.'
          : 'Le test n\'a pas pu démarrer. Réessayez.';
      },
    });
  }

  /** Coche ou décoche une option. Un QCM à réponse unique n'en garde qu'une. */
  basculer(option: string): void {
    if (this.question?.kind === 'QCM_MULTIPLE') {
      this.choix.has(option) ? this.choix.delete(option) : this.choix.add(option);
    } else {
      this.choix = this.choix.has(option) ? new Set() : new Set([option]);
    }
  }

  estChoisi(option: string): boolean {
    return this.choix.has(option);
  }

  get peutValider(): boolean {
    if (this.envoi) return false;
    return this.question?.kind === 'REPONSE_COURTE'
      ? this.reponseCourte.trim().length > 0
      : this.choix.size > 0;
  }

  valider(): void {
    if (!this.peutValider) return;
    const reponse = this.question?.kind === 'REPONSE_COURTE'
      ? [this.reponseCourte.trim()]
      : [...this.choix];
    this.envoyer(reponse);
  }

  /** « Passer » compte comme une erreur — l'écran le dit avant le clic. */
  passer(): void {
    if (this.envoi) return;
    this.envoyer(null);
  }

  private envoyer(reponse: string[] | null): void {
    if (!this.question) return;
    this.envoi = true;
    this.assessment.publicAnswer(this.token, this.question.position, reponse).subscribe({
      next: (res) => {
        this.envoi = false;
        this.appliquer(res.next_question, res.finished);
      },
      error: (err) => {
        this.envoi = false;
        if (err?.status === 410) {
          // Temps écoulé : le serveur a clos et corrigé la session en l'état.
          this.terminer();
          return;
        }
        this.erreur = err?.error?.detail || "La réponse n'a pas pu être enregistrée.";
      },
    });
  }

  private appliquer(question: PublicQuestion | null, fini: boolean): void {
    this.erreur = '';
    this.choix = new Set();
    this.reponseCourte = '';

    if (fini || !question) { this.terminer(); return; }

    this.question = question;
    this.etape = 'question';
    this.secondesRestantes = question.seconds_remaining;
    this.demarrerMinuteur();
  }

  private terminer(): void {
    this.arreterMinuteur();
    this.question = null;
    this.etape = 'termine';
    // Best-effort : la session est déjà notée côté serveur si tout a été traité.
    this.assessment.publicFinish(this.token).subscribe({ error: () => {} });
  }

  private demarrerMinuteur(): void {
    this.arreterMinuteur();
    this.minuteur = setInterval(() => {
      this.secondesRestantes = Math.max(0, this.secondesRestantes - 1);
      if (this.secondesRestantes === 0) {
        // Purement indicatif : c'est le serveur qui referme réellement.
        this.arreterMinuteur();
        this.terminer();
      }
    }, 1000);
  }

  private arreterMinuteur(): void {
    if (this.minuteur) { clearInterval(this.minuteur); this.minuteur = undefined; }
  }

  get tempsAffiche(): string {
    const m = Math.floor(this.secondesRestantes / 60);
    const s = this.secondesRestantes % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  /** Sous deux minutes, le décompte passe en alerte. */
  get tempsCritique(): boolean {
    return this.secondesRestantes > 0 && this.secondesRestantes <= 120;
  }

  get progression(): number {
    if (!this.question) return 0;
    return Math.round((this.question.position - 1) / this.question.total * 100);
  }
}
