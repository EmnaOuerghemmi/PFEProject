import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { InvitationResponse } from '../../../core/services/recruitment.service';
import { InterviewManagerComponent } from './interview-manager.component';

/**
 * Quand proposer d'évaluer un entretien.
 *
 * La règle tient en une phrase, et chacun de ses termes compte : le bouton
 * n'apparaît qu'après la **fin** du créneau, et seulement pour un entretien
 * **confirmé**.
 *
 * Se caler sur le DÉBUT inviterait à noter quelqu'un qu'on est en train
 * d'écouter. Et un créneau proposé mais non confirmé n'a jamais eu lieu — le
 * candidat ne s'est peut-être même pas manifesté.
 */
function invitation(over: Partial<InvitationResponse> = {}): InvitationResponse {
  return {
    id: 'inv-1',
    application_id: 'app-1',
    token: 'jeton',
    status: 'CONFIRMED',
    message: null,
    expires_at: '2026-09-01T00:00:00Z',
    confirmed_slot_id: 'slot-1',
    confirmed_at: '2026-08-20T10:00:00Z',
    cancelled_at: null,
    cancellation_reason: null,
    created_at: '2026-08-19T10:00:00Z',
    updated_at: '2026-08-20T10:00:00Z',
    slots: [],
    candidate_name: 'Emna Ouerghemmi',
    candidate_email: 'emna@example.tn',
    job_title: 'Développeur Laravel',
    public_url: 'https://example.tn/i/jeton',
    meet_url: null,
    ...over,
  } as InvitationResponse;
}

function creneau(debutMs: number, dureeMin = 30) {
  return [{
    id: 'slot-1',
    invitation_id: 'inv-1',
    start_at: new Date(debutMs).toISOString(),
    end_at: new Date(debutMs + dureeMin * 60_000).toISOString(),
    is_selected: true,
  }];
}

const MINUTE = 60_000;

describe('InterviewManagerComponent — quand évaluer', () => {
  let composant: InterviewManagerComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewManagerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    composant = TestBed.createComponent(InterviewManagerComponent).componentInstance;
  });

  it('propose d évaluer un entretien terminé', () => {
    const inv = invitation({ slots: creneau(Date.now() - 120 * MINUTE) });
    expect(composant.entretienPasse(inv)).toBeTrue();
  });

  it('ne propose rien avant le rendez-vous', () => {
    const inv = invitation({ slots: creneau(Date.now() + 120 * MINUTE) });
    expect(composant.entretienPasse(inv)).toBeFalse();
  });

  it('ne propose rien PENDANT le rendez-vous', () => {
    // Le cas qui justifie de se caler sur la fin plutôt que sur le début :
    // l'entretien a commencé il y a dix minutes et dure une demi-heure.
    const inv = invitation({ slots: creneau(Date.now() - 10 * MINUTE, 30) });
    expect(composant.entretienPasse(inv)).toBeFalse();
  });

  it('propose dès la minute qui suit la fin', () => {
    const inv = invitation({ slots: creneau(Date.now() - 31 * MINUTE, 30) });
    expect(composant.entretienPasse(inv)).toBeTrue();
  });

  it('ne propose rien pour une invitation non confirmée', () => {
    // Le créneau est passé, mais le candidat ne l'a jamais accepté : il n'y a
    // pas eu d'entretien à évaluer.
    const inv = invitation({
      status: 'PENDING',
      slots: creneau(Date.now() - 120 * MINUTE),
    });
    expect(composant.entretienPasse(inv)).toBeFalse();
  });

  it('ne propose rien pour une invitation annulée', () => {
    const inv = invitation({
      status: 'CANCELLED',
      slots: creneau(Date.now() - 120 * MINUTE),
    });
    expect(composant.entretienPasse(inv)).toBeFalse();
  });

  it('ne casse pas quand aucun créneau n est retenu', () => {
    const sansSelection = creneau(Date.now() - 120 * MINUTE);
    sansSelection[0].is_selected = false;
    expect(composant.entretienPasse(invitation({ slots: sansSelection }))).toBeFalse();
    expect(composant.entretienPasse(invitation({ slots: [] }))).toBeFalse();
  });

  // ── Durée de vie du lien visio ─────────────────────────────────────────
  //
  // Le lien reste une journée après l'entretien, puis disparaît : au-delà, la
  // salle est vide et le bouton ne mène nulle part.

  const JOUR = 24 * 60 * MINUTE;

  it('propose le lien avant le rendez-vous', () => {
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() + 120 * MINUTE),
    });
    expect(composant.lienVisioUtile(inv)).toBeTrue();
  });

  it('propose le lien pendant le rendez-vous', () => {
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() - 10 * MINUTE, 30),
    });
    expect(composant.lienVisioUtile(inv)).toBeTrue();
  });

  it('garde le lien dans l heure qui suit', () => {
    // Une connexion qui lâche, un entretien qui déborde : couper net à l'heure
    // dite retirerait le lien au moment où il sert encore.
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() - 90 * MINUTE, 30),
    });
    expect(composant.lienVisioUtile(inv)).toBeTrue();
  });

  it('retire le lien passé une journée', () => {
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() - 2 * JOUR, 30),
    });
    expect(composant.lienVisioUtile(inv)).toBeFalse();
  });

  it('retire le lien juste après la limite', () => {
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() - JOUR - 40 * MINUTE, 30),
    });
    expect(composant.lienVisioUtile(inv)).toBeFalse();
  });

  it('ne propose rien sans lien enregistré', () => {
    // Les entretiens antérieurs à la génération de lien n'en ont pas.
    const inv = invitation({ meet_url: null, slots: creneau(Date.now()) });
    expect(composant.lienVisioUtile(inv)).toBeFalse();
  });

  it('garde le lien quand aucun créneau n est retenu', () => {
    // On ne sait pas s'il est périmé : le retirer par précaution supprimerait
    // une fonction qui marche.
    const inv = invitation({ meet_url: 'https://meet.jit.si/piqbit-x', slots: [] });
    expect(composant.lienVisioUtile(inv)).toBeTrue();
  });

  it('un entretien de la veille garde son lien mais propose déjà l évaluation', () => {
    // Les deux règles se recouvrent volontairement : le lien meurt à 24 h,
    // l'évaluation s'ouvre dès la fin du créneau.
    const inv = invitation({
      meet_url: 'https://meet.jit.si/piqbit-x',
      slots: creneau(Date.now() - 3 * 60 * MINUTE, 30),
    });
    expect(composant.lienVisioUtile(inv)).toBeTrue();
    expect(composant.entretienPasse(inv)).toBeTrue();
  });

  // ── Ouverture de la modale ─────────────────────────────────────────────────

  it('ouvre l évaluation sur la bonne candidature', () => {
    const inv = invitation({
      application_id: 'app-42',
      slots: creneau(Date.now() - 120 * MINUTE),
    });
    composant.ouvrirEvaluation(inv);

    expect(composant.evaluationApplicationId).toBe('app-42');
    expect(composant.evaluationCandidat).toBe('Emna Ouerghemmi');
  });

  it('n empêche pas d ouvrir quand le nom manque', () => {
    const inv = invitation({
      candidate_name: null,
      slots: creneau(Date.now() - 120 * MINUTE),
    });
    composant.ouvrirEvaluation(inv);
    expect(composant.evaluationCandidat).toBe('ce candidat');
  });

  it('fermer libère la candidature sélectionnée', () => {
    composant.ouvrirEvaluation(invitation({ slots: creneau(Date.now() - MINUTE) }));
    composant.fermerEvaluation();
    expect(composant.evaluationApplicationId).toBeNull();
  });
});
