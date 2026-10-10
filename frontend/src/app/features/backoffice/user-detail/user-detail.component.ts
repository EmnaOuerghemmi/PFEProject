import { Component, OnInit, inject } from '@angular/core';
import { roleLabel } from '../../../core/models/user.model';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { SafePipe } from '../../../core/pipes/safe.pipe';

import {
  ProfileApplication, UserProfile, UserService,
} from '../../../core/services/user.service';
import {
  APPLICATION_STATUS_META, applicationStatusColor, RecruitmentService,
} from '../../../core/services/recruitment.service';

/**
 * Fiche d'un utilisateur, côté administration.
 *
 * La page prend deux formes, décidées par le serveur :
 *
 * * **Un candidat** — son compte, son dossier, ses candidatures avec leurs
 *   scores et l'état de ses tests.
 * * **Un compte interne** — son compte seul. Un RH n'a pas de candidatures ;
 *   afficher des sections vides laisserait croire à un chargement raté.
 *
 * Ce qu'on n'y trouve pas, volontairement : le détail des réponses aux tests.
 * Il se consulte depuis l'écran Test technique, qui l'accompagne de son
 * contexte — le recopier ici en ferait une seconde source à maintenir.
 */
type Etape = 'chargement' | 'pret' | 'erreur';

const ETATS_TEST: Record<string, string> = {
  ENVOYE: 'Envoyé, non ouvert',
  EN_COURS: 'En cours',
  TERMINE: 'Terminé',
  EXPIRE: 'Temps écoulé',
  ABANDONNE: 'Lien expiré',
};

@Component({
  selector: 'app-user-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, SafePipe],
  templateUrl: './user-detail.component.html',
  styleUrls: ['./user-detail.component.css'],
})
export class UserDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private users = inject(UserService);
  private recruitment = inject(RecruitmentService);

  etape: Etape = 'chargement';
  erreur = '';
  profil: UserProfile | null = null;

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    if (!id) {
      this.etape = 'erreur';
      this.erreur = 'Utilisateur introuvable.';
      return;
    }
    this.users.getUserProfile(id).subscribe({
      next: (p) => { this.profil = p; this.etape = 'pret'; },
      error: (err) => {
        this.etape = 'erreur';
        this.erreur = err?.status === 404
          ? "Cet utilisateur n'existe pas ou a été supprimé."
          : 'La fiche n\'a pas pu être chargée.';
      },
    });
  }

  // ── Compte ──────────────────────────────────────────────────────────────────

  libelleRole(role: string): string { return roleLabel(role); }

  get initiales(): string {
    const nom = this.profil?.account.full_name
             || this.profil?.account.username
             || '?';
    const parties = nom.trim().split(/\s+/);
    return ((parties[0]?.[0] || '') + (parties[1]?.[0] || '')).toUpperCase()
        || nom.slice(0, 2).toUpperCase();
  }

  // ── Candidatures ────────────────────────────────────────────────────────────

  libelleTest(statut: string): string { return ETATS_TEST[statut] || statut; }

  couleurStatut(statut: string): string { return applicationStatusColor(statut); }

  /** Vrai quand le test a réellement été rendu — pas seulement envoyé. */
  testRendu(app: ProfileApplication): boolean {
    return app.test?.status === 'TERMINE' || app.test?.status === 'EXPIRE';
  }

  /**
   * Ton d'un score, pour la pastille. Les bornes sont celles employées
   * ailleurs dans le back-office, pour qu'un même chiffre ne change pas de
   * couleur d'un écran à l'autre.
   */
  ton(score: number | null | undefined): string {
    if (score == null) return 'vide';
    if (score >= 75) return 'haut';
    if (score >= 50) return 'moyen';
    return 'bas';
  }

  /** Le composite n'a de sens qu'accompagné du nombre de volets. */
  completude(app: ProfileApplication): string {
    return app.composite_completeness
      ? `${app.composite_completeness}/3 volets`
      : '';
  }

  readonly statutMeta = APPLICATION_STATUS_META;

  // ── Aperçu du CV de référence ───────────────────────────────────────────
  //
  // Même mécanisme que l'écran Candidatures : le fichier est chargé en blob,
  // authentifié, plutôt que pointé par une URL brute qu'on collerait dans un
  // <iframe> — ce qui exposerait le jeton de session dans l'historique de
  // navigation.

  cvPreviewOpen = false;
  cvPreviewUrl = '';
  cvPreviewErreur = '';

  ouvrirApercuCv(cheminCv: string): void {
    this.cvPreviewErreur = '';
    this.recruitment.downloadCVAsBlob(cheminCv).subscribe({
      next: (blob) => {
        this.cvPreviewUrl = URL.createObjectURL(blob);
        this.cvPreviewOpen = true;
      },
      error: () => { this.cvPreviewErreur = "Le CV n'a pas pu être chargé."; },
    });
  }

  fermerApercuCv(): void {
    if (this.cvPreviewUrl.startsWith('blob:')) {
      URL.revokeObjectURL(this.cvPreviewUrl);
    }
    this.cvPreviewOpen = false;
    this.cvPreviewUrl = '';
  }

  suivre(_: number, app: ProfileApplication): string { return app.id; }
}
