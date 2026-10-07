import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import {
  Application, JobOffer, RecruitmentService, applicationStatusLabel,
} from '../../../core/services/recruitment.service';
import { QuestionBankComponent } from './question-bank.component';
import { SessionReviewComponent } from './session-review.component';
import { TestDispatchComponent } from './test-dispatch.component';
import { InterviewSchedulerComponent } from '../../../shared/components/interview-scheduler/interview-scheduler.component';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';

/**
 * Test technique — poste de travail du RH.
 *
 * Tout part d'une offre, parce que le vivier de questions appartient à l'offre
 * et non au candidat : les mêmes questions servent à tous ceux qui postulent,
 * sans quoi les scores ne se compareraient pas.
 *
 * Deux onglets, dans l'ordre où le travail se fait :
 *
 * * **Vivier** — générer, relire, mettre en service. À faire une fois par
 *   offre, avant tout envoi.
 * * **Candidats** — préparer un test, l'envoyer, relire les résultats,
 *   saisir l'entretien.
 *
 * Le candidat n'a accès à aucun de ces écrans : il ne voit ni sa note, ni sa
 * correction, ni les temps mesurés.
 */
type Onglet = 'vivier' | 'candidats';
type Volet = 'preparer' | 'resultats';

@Component({
  selector: 'app-assessment',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    QuestionBankComponent, TestDispatchComponent, SessionReviewComponent, InterviewSchedulerComponent,
    SelectComponent],
  templateUrl: './assessment.component.html',
  styleUrls: ['./assessment.component.css'],
})
export class AssessmentComponent implements OnInit {
  private recruitment = inject(RecruitmentService);
  private route = inject(ActivatedRoute);

  offres: JobOffer[] = [];
  /** Options du sélecteur d'offre — un champ rempli au chargement, pas un getter. */
  offreOptions: SelectOption[] = [];
  offreId = '';
  chargementOffres = false;

  candidatures: Application[] = [];
  candidatureId = '';
  chargementCandidatures = false;

  onglet: Onglet = 'vivier';
  volet: Volet = 'preparer';
  erreur = '';
  message = '';

  /**
   * Offre et candidature demandées par l'URL.
   *
   * On arrive ici depuis le classement d'une offre, via « Envoyer le test ».
   * Sans les honorer, la redirection retomberait sur la première offre de la
   * liste et le RH devrait tout resélectionner — ce qui vide la manœuvre de
   * son intérêt.
   */
  private offreDemandee = '';
  private candidatureDemandee = '';

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    this.offreDemandee = params.get('job') ?? '';
    this.candidatureDemandee = params.get('application') ?? '';
    if (this.candidatureDemandee) this.onglet = 'candidats';
    this.chargerOffres();
  }

  chargerOffres(): void {
    this.chargementOffres = true;
    // Le listing de gestion : on prépare souvent le vivier d'une offre qui
    // n'est pas encore publiée.
    this.recruitment.getJobsForManagement(1, 100).subscribe({
      next: (page) => {
        this.chargementOffres = false;
        this.offres = page.items;
        this.offreOptions = this.offres.map((o) => ({ value: o.id, label: o.title }));
        const voulue = this.offres.find((o) => o.id === this.offreDemandee);
        if (voulue) {
          this.choisirOffre(voulue.id);
        } else if (this.offres.length && !this.offreId) {
          this.choisirOffre(this.offres[0].id);
        }
      },
      error: () => {
        this.chargementOffres = false;
        this.erreur = 'Les offres n\'ont pas pu être chargées.';
      },
    });
  }

  choisirOffre(id: string): void {
    this.offreId = id;
    this.candidatureId = '';
    this.candidatures = [];
    this.message = '';
    if (id) this.chargerCandidatures();
  }

  chargerCandidatures(): void {
    this.chargementCandidatures = true;
    this.recruitment.getApplicationsByJob(this.offreId).subscribe({
      next: (apps) => {
        this.chargementCandidatures = false;
        this.candidatures = apps;
        const voulue = apps.find((a) => a.id === this.candidatureDemandee);
        if (voulue) {
          this.choisirCandidature(voulue);
          // Consommée : un rechargement manuel de la liste ne doit pas
          // réimposer la sélection au RH qui vient d'en choisir une autre.
          this.candidatureDemandee = '';
        }
      },
      error: () => {
        this.chargementCandidatures = false;
        this.erreur = 'Les candidatures n\'ont pas pu être chargées.';
      },
    });
  }

  choisirCandidature(app: Application): void {
    this.candidatureId = app.id;
    this.message = '';
    // Un test déjà parti : on ouvre directement sur les résultats.
    this.volet = this.testDejaEnvoye(app) ? 'resultats' : 'preparer';
  }

  /** Après un envoi : on rafraîchit la liste et on bascule sur le suivi. */
  surEnvoi(): void {
    this.message = 'Test envoyé — le candidat a reçu son lien par e-mail.';
    this.volet = 'resultats';
    this.chargerCandidatures();
  }

  // ── Confort d'affichage ─────────────────────────────────────────────────────

  get offre(): JobOffer | undefined {
    return this.offres.find((o) => o.id === this.offreId);
  }

  get competences(): string[] {
    return this.offre?.required_skills ?? [];
  }

  get candidature(): Application | undefined {
    return this.candidatures.find((a) => a.id === this.candidatureId);
  }

  /**
   * Statuts postérieurs à l'envoi d'un test — ils décident de l'onglet sur
   * lequel la candidature s'ouvre. La liste locale d'avant citait `REVIEWING`,
   * `SHORTLISTED` et `OFFER`, que le serveur ne produit pas.
   */
  testDejaEnvoye(app: Application): boolean {
    return ['TEST_SENT', 'EN_TEST', 'TEST_DONE', 'INTERVIEW_SCHEDULED',
            'NEGOTIATION', 'ACCEPTED', 'HIRED'].includes(app.status);
  }

  libelleStatut(statut: string): string {
    return applicationStatusLabel(statut);
  }

  /**
   * Organiser un entretien.
   *
   * On réutilise `InterviewSchedulerComponent`, déjà employé depuis la fiche
   * d'offre : proposer des créneaux, envoyer l'invitation et suivre la réponse
   * du candidat sont trois choses qu'il sait faire. En réécrire une seconde
   * version ferait deux implémentations du même geste — et renvoyer vers la
   * page Entretiens ne marcherait pas : elle affiche, elle ne crée pas.
   */
  planificateurOuvert = false;

  lancerEntretien(): void {
    this.planificateurOuvert = true;
  }

  surPlanificateurFerme(succes: boolean): void {
    this.planificateurOuvert = false;
    if (succes) {
      this.message = "Entretien planifié — le candidat a reçu son invitation. "
                   + "Vous l'évaluerez depuis la page Entretiens, une fois passé.";
      this.chargerCandidatures();
    }
  }

  suivreApp(_: number, app: Application): string { return app.id; }
}
