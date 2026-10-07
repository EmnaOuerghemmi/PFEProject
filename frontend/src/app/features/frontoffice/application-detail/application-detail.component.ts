import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  ApplicationScoreDetail, CandidateFeedbackService,
} from '../../../core/services/candidate-feedback.service';
import {
  JobRecommendation, RecruitmentService,
  WORK_MODE_LABELS, contractTypesLabel,
} from '../../../core/services/recruitment.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { ToastService } from '../../../core/services/toast.service';

/**
 * Détail de sa candidature — page du candidat.
 *
 * Trois partis pris, qui tiennent toute la page :
 *
 * 1. **Des faits, pas un verdict.** Le score dit à quel point un CV
 *    correspond à une liste de critères. Il ne dit rien des capacités de la
 *    personne, et il ne décide de rien : un recruteur examine chaque dossier.
 *    La page le répète, parce qu'un chiffre sur 100 est toujours lu comme une
 *    note.
 * 2. **Les limites sont annoncées.** La correspondance est littérale :
 *    « PostgreSQL » et « SQL » sont deux mots différents. Le taire ferait
 *    passer l'outil pour incapable de lire le CV qu'on vient de lui confier.
 * 3. **Ce qui n'est pas partagé n'existe pas ici.** Le serveur omet la note de
 *    test et le retour d'entretien tant que le recrutement ne les a pas
 *    ouverts. La page n'affiche donc ni section grisée, ni « non communiqué » —
 *    ce serait apprendre au candidat qu'on lui cache quelque chose.
 */
type Etape = 'chargement' | 'pret' | 'erreur';

const BANDES: Record<string, string> = {
  forte: 'Correspondance forte',
  bonne: 'Bonne correspondance',
  partielle: 'Correspondance partielle',
  faible: 'Correspondance faible',
};

const STATUTS: Record<string, string> = {
  PENDING: 'Candidature reçue',
  REVIEWED: 'CV examiné',
  TEST_SENT: 'Test technique envoyé',
  EN_TEST: 'Test en cours',
  TEST_DONE: 'Test passé',
  INTERVIEW_SCHEDULED: 'Entretien planifié',
  NEGOTIATION: 'Discussion en cours',
  ON_HOLD: 'Candidature conservée en réserve',
  ACCEPTED: 'Candidature retenue',
  HIRED: 'Recrutement confirmé',
  REJECTED: 'Candidature non retenue',
  WITHDRAWN: 'Candidature retirée',
};

/** Les étapes du parcours, dans l'ordre — pour la frise. */
const PARCOURS = ['PENDING', 'REVIEWED', 'TEST_SENT', 'INTERVIEW_SCHEDULED',
                  'ACCEPTED'];

/** Fins de parcours : aucune action de retrait ni de transition n'en sort —
 *  même vocabulaire que `app/models/application_status.py` côté serveur. */
const TERMINAUX = new Set(['HIRED', 'REJECTED', 'WITHDRAWN']);

@Component({
  selector: 'app-application-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './application-detail.component.html',
  styleUrls: ['./application-detail.component.css'],
})
export class ApplicationDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(CandidateFeedbackService);
  private recruitment = inject(RecruitmentService);
  private confirm = inject(ConfirmService);
  private toast = inject(ToastService);

  etape: Etape = 'chargement';
  erreur = '';
  detail: ApplicationScoreDetail | null = null;
  retraitEnCours = false;

  /** Offres compatibles avec le dernier CV analysé du candidat. Vide tant
   *  qu'aucune n'atteint le seuil — la section n'est alors pas rendue. */
  recommandations: JobRecommendation[] = [];

  readonly bandes = BANDES;

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    if (!id) {
      this.etape = 'erreur';
      this.erreur = 'Candidature introuvable.';
      return;
    }
    this.chargerRecommandations();
    this.service.scoreDetail(id).subscribe({
      next: (d) => {
        this.detail = d;
        this.etape = 'pret';
      },
      error: (err) => {
        this.etape = 'erreur';
        // 404 couvre « inexistante » ET « pas la vôtre » : le serveur ne les
        // distingue pas, pour qu'on ne puisse pas énumérer les dossiers des
        // autres. Le message reste donc volontairement neutre.
        this.erreur = err?.status === 404
          ? "Cette candidature n'existe pas ou ne vous appartient pas."
          : 'Impossible de charger votre candidature. Réessayez dans un instant.';
      },
    });
  }

  // ── Offres recommandées ─────────────────────────────────────────────────────

  /**
   * Chargée à part du dossier, et sans bloquer son affichage : une
   * recommandation est un bonus. Si l'appel échoue, la liste reste vide et la
   * page fait ce pour quoi le candidat est venu — montrer sa candidature.
   */
  private chargerRecommandations(): void {
    this.recruitment.getMyRecommendedJobs().subscribe({
      next: (offres) => (this.recommandations = offres),
      error: () => (this.recommandations = []),
    });
  }

  voirOffre(jobId: string): void {
    this.router.navigate(['/frontoffice/job', jobId]);
  }

  modeLibelle(offre: JobRecommendation): string {
    return offre.work_mode ? WORK_MODE_LABELS[offre.work_mode] : '';
  }

  contratLibelle(offre: JobRecommendation): string {
    return contractTypesLabel(offre.contract_types ?? null);
  }

  suivreOffre(_: number, offre: JobRecommendation): string {
    return offre.job_id;
  }

  // ── Lecture ─────────────────────────────────────────────────────────────────

  get bandeLibelle(): string {
    return BANDES[this.detail?.band ?? ''] ?? 'Correspondance';
  }

  libelleStatut(statut: string): string {
    return STATUTS[statut] || statut;
  }

  /** Rejetée ou retirée : la pastille de statut n'a plus rien de positif à
   *  afficher en teal. */
  statutEstNegatif(statut: string): boolean {
    return statut === 'REJECTED' || statut === 'WITHDRAWN';
  }

  /** Le retrait n'a de sens que tant que le dossier est encore actif. */
  get peutRetirer(): boolean {
    return !!this.detail && !TERMINAUX.has(this.detail.status);
  }

  /** Pourcentage arrondi d'une pondération — `0.5` devient `50`. */
  poids(valeur: number | null | undefined): number | null {
    return valeur == null ? null : Math.round(valeur * 100);
  }

  get aDesPoids(): boolean {
    const p = this.detail?.weights;
    return !!p && (p.skills != null || p.experience != null || p.education != null);
  }

  /** Nombre de compétences demandées, tous statuts confondus. */
  get totalCompetences(): number {
    const d = this.detail;
    if (!d) return 0;
    return d.skills_required.length
        || d.skills_matched.length + d.skills_missing.length;
  }

  // ── Parcours ────────────────────────────────────────────────────────────────

  get etapesParcours(): { cle: string; libelle: string; etat: string }[] {
    const courant = this.detail?.status ?? 'PENDING';
    // Un refus — ou un retrait — ferme le parcours là où il en était :
    // afficher les étapes suivantes comme « à venir » serait un faux espoir.
    if (courant === 'REJECTED' || courant === 'WITHDRAWN') {
      return [{ cle: courant, libelle: STATUTS[courant], etat: 'clos' }];
    }
    const index = this.indexParcours(courant);
    return PARCOURS.map((cle, i) => ({
      cle,
      libelle: STATUTS[cle],
      etat: i < index ? 'fait' : i === index ? 'courant' : 'a-venir',
    }));
  }

  /** Les statuts intermédiaires se rattachent à l'étape qui les contient. */
  private indexParcours(statut: string): number {
    const equivalences: Record<string, string> = {
      EN_TEST: 'TEST_SENT', TEST_DONE: 'TEST_SENT',
      NEGOTIATION: 'INTERVIEW_SCHEDULED', ON_HOLD: 'INTERVIEW_SCHEDULED', HIRED: 'ACCEPTED',
    };
    const cle = equivalences[statut] ?? statut;
    const i = PARCOURS.indexOf(cle);
    return i === -1 ? 0 : i;
  }

  // ── Retrait ─────────────────────────────────────────────────────────────────

  async retirerCandidature(): Promise<void> {
    if (!this.detail || this.retraitEnCours) return;
    const ok = await this.confirm.ask({
      title: 'Retirer votre candidature ?',
      message: `Vous ne postulerez plus pour « ${this.detail.job_title} ». `
        + `Cette action est définitive — vous pourrez déposer une nouvelle `
        + `candidature pour cette offre si elle est toujours ouverte.`,
      confirmLabel: 'Retirer ma candidature',
      danger: true,
    });
    if (!ok) return;

    this.retraitEnCours = true;
    this.service.withdraw(this.detail.application_id).subscribe({
      next: () => {
        this.retraitEnCours = false;
        if (this.detail) this.detail = { ...this.detail, status: 'WITHDRAWN' };
        this.toast.success('Votre candidature a été retirée.');
      },
      error: (err) => {
        this.retraitEnCours = false;
        this.toast.fromHttpError(err, 'Impossible de retirer cette candidature.');
      },
    });
  }

  // ── CV envoyé ───────────────────────────────────────────────────────────────

  previewCv(): void {
    const path = this.detail?.cv_file_path;
    if (!path) return;
    this.recruitment.downloadCVAsBlob(path).subscribe({
      next: (blob) => window.open(URL.createObjectURL(blob), '_blank'),
      error: (err) => this.toast.fromHttpError(err, 'Impossible de charger le CV.'),
    });
  }

  downloadCv(): void {
    const path = this.detail?.cv_file_path;
    if (!path) return;
    this.recruitment.downloadCVAsBlob(path).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cv_${this.detail?.application_id ?? 'candidature'}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      },
      error: (err) => this.toast.fromHttpError(err, 'Le téléchargement du CV a échoué.'),
    });
  }

  /** Les listes de cette page tiennent soit des chaînes, soit des étapes. */
  suivre(_: number, valeur: string | { cle: string }): string {
    return typeof valeur === 'string' ? valeur : valeur.cle;
  }
}
