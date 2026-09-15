import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  ApplicationScoreDetail, CandidateFeedbackService,
} from '../../../core/services/candidate-feedback.service';

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
  ACCEPTED: 'Candidature retenue',
  HIRED: 'Recrutement confirmé',
  REJECTED: 'Candidature non retenue',
};

/** Les étapes du parcours, dans l'ordre — pour la frise. */
const PARCOURS = ['PENDING', 'REVIEWED', 'TEST_SENT', 'INTERVIEW_SCHEDULED',
                  'ACCEPTED'];

@Component({
  selector: 'app-application-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './application-detail.component.html',
  styleUrls: ['./application-detail.component.css'],
})
export class ApplicationDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private service = inject(CandidateFeedbackService);

  etape: Etape = 'chargement';
  erreur = '';
  detail: ApplicationScoreDetail | null = null;

  readonly bandes = BANDES;

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    if (!id) {
      this.etape = 'erreur';
      this.erreur = 'Candidature introuvable.';
      return;
    }
    this.service.scoreDetail(id).subscribe({
      next: (d) => { this.detail = d; this.etape = 'pret'; },
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

  // ── Lecture ─────────────────────────────────────────────────────────────────

  get bandeLibelle(): string {
    return BANDES[this.detail?.band ?? ''] ?? 'Correspondance';
  }

  libelleStatut(statut: string): string {
    return STATUTS[statut] || statut;
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
    // Un refus ferme le parcours là où il en était : afficher les étapes
    // suivantes comme « à venir » serait un faux espoir.
    if (courant === 'REJECTED') {
      return [{ cle: 'REJECTED', libelle: STATUTS['REJECTED'], etat: 'clos' }];
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
      NEGOTIATION: 'INTERVIEW_SCHEDULED', HIRED: 'ACCEPTED',
    };
    const cle = equivalences[statut] ?? statut;
    const i = PARCOURS.indexOf(cle);
    return i === -1 ? 0 : i;
  }

  /** Les listes de cette page tiennent soit des chaînes, soit des étapes. */
  suivre(_: number, valeur: string | { cle: string }): string {
    return typeof valeur === 'string' ? valeur : valeur.cle;
  }
}
