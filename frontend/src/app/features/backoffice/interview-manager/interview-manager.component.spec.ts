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

/**
 * Onglets par étape. L'étape vient du serveur ; l'écran se contente de ranger,
 * trier, et de réserver « À évaluer » aux membres de l'entretien.
 */
describe('InterviewManagerComponent — onglets par étape', () => {
  let composant: InterviewManagerComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewManagerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    composant = TestBed.createComponent(InterviewManagerComponent).componentInstance;
  });

  function charger(liste: InvitationResponse[]) {
    composant.invitations = liste;
    composant.computeKpis();
    composant.rebuild();
  }

  const ids = () => composant.filtered.map(i => i.id);

  it('s ouvre sur « À venir »', () => {
    expect(composant.onglet).toBe('A_VENIR');
  });

  it('« À venir » trie du rendez-vous le plus proche au plus lointain', () => {
    charger([
      invitation({ id: 'loin', stage: 'A_VENIR', slots: creneau(Date.now() + 5 * 24 * 60 * MINUTE) }),
      invitation({ id: 'proche', stage: 'A_VENIR', slots: creneau(Date.now() + 60 * MINUTE) }),
      invitation({ id: 'attente', stage: 'EN_ATTENTE', status: 'PENDING' }),
    ]);
    expect(ids()).toEqual(['proche', 'loin']);
  });

  it('« À évaluer » est réservé aux membres de l entretien', () => {
    charger([
      invitation({ id: 'moi', stage: 'A_EVALUER', can_evaluate: true }),
      invitation({ id: 'autre', stage: 'A_EVALUER', can_evaluate: false }),
    ]);
    composant.selectTab('PASSES');
    expect(ids()).toEqual(['moi']);
    expect(composant.countAEvaluer).toBe(1);
    expect(composant.countAutresAEvaluer).toBe(1);
  });

  it('« Évalués » montre les entretiens notés, qu on en soit membre ou non', () => {
    charger([
      invitation({ id: 'e1', stage: 'EVALUE', can_evaluate: false, slots: creneau(Date.now() - 5 * 24 * 60 * MINUTE) }),
      invitation({ id: 'e2', stage: 'EVALUE', can_evaluate: true, slots: creneau(Date.now() - 2 * 24 * 60 * MINUTE) }),
      invitation({ id: 'a', stage: 'A_EVALUER', can_evaluate: true }),
    ]);
    composant.selectTab('PASSES');
    composant.selectSousOnglet('EVALUES');
    expect(ids()).toEqual(['e2', 'e1']);   // l'entretien le plus récent d'abord
  });

  it('« Annulées » regroupe les candidats absents et les annulations', () => {
    charger([
      invitation({ id: 'absent', stage: 'ABSENT', status: 'EXPIRED' }),
      invitation({ id: 'annule', stage: 'ANNULE', status: 'CANCELLED', cancelled_at: '2026-09-30T10:00:00Z' }),
      invitation({ id: 'attente', stage: 'EN_ATTENTE', status: 'PENDING' }),
    ]);
    composant.selectTab('ANNULES');
    expect(ids().sort()).toEqual(['absent', 'annule']);
    expect(composant.countFor('ANNULES')).toBe(2);
  });

  it('traduit le motif d un remplacement automatique', () => {
    const inv = invitation({ stage: 'ANNULE', cancellation_reason: 'Superseded by new invitation' });
    expect(composant.motifAnnulation(inv)).toBe('Remplacé par une nouvelle invitation');
  });

  it('après une évaluation, propose d accepter le candidat', () => {
    const inv = invitation({ application_id: 'app-7', job_offer_id: 'job-1', application_status: 'INTERVIEW_SCHEDULED' });
    composant.ouvrirEvaluation(inv);
    composant.surEvaluationEnregistree({ interview_score: 74 } as any);

    expect(composant.evaluationApplicationId).toBeNull();
    expect(composant.suite?.applicationId).toBe('app-7');
    expect(composant.suite?.note).toBe(74);
    expect(composant.suite?.acceptable).toBeTrue();
  });

  it('ne propose pas d accepter un candidat déjà accepté ou rejeté', () => {
    composant.ouvrirEvaluation(invitation({ application_status: 'ACCEPTED' }));
    composant.surEvaluationEnregistree();
    expect(composant.suite?.acceptable).toBeFalse();
    expect(composant.suite?.acceptee).toBeTrue();

    composant.ouvrirEvaluation(invitation({ application_status: 'REJECTED' }));
    composant.surEvaluationEnregistree();
    expect(composant.suite?.acceptable).toBeFalse();
  });
});

/**
 * Le repère de temps au pied de la carte : une seule phrase, celle qui compte
 * à l'étape de l'entretien.
 */
describe('InterviewManagerComponent — repère de temps des cartes', () => {
  let composant: InterviewManagerComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewManagerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    composant = TestBed.createComponent(InterviewManagerComponent).componentInstance;
  });

  const JOUR = 24 * 60 * MINUTE;

  it("annonce dans combien de temps commence un entretien à venir", () => {
    const inv = invitation({ stage: 'A_VENIR', slots: creneau(Date.now() + 3 * JOUR + 5 * MINUTE) });
    expect(composant.repereTemps(inv)).toBe('Dans 3 j');
  });

  it("dit « En cours » pendant le rendez-vous", () => {
    const inv = invitation({ stage: 'A_VENIR', slots: creneau(Date.now() - 10 * MINUTE, 30) });
    expect(composant.repereTemps(inv)).toBe('En cours');
  });

  it("dit depuis quand un entretien est terminé", () => {
    // Le repère se compte depuis la FIN du créneau (30 min après son début).
    const inv = invitation({ stage: 'A_EVALUER', slots: creneau(Date.now() - 3 * JOUR - 60 * MINUTE) });
    expect(composant.repereTemps(inv)).toBe('Terminé il y a 3 jours');
  });

  it("dit quand l'évaluation a été faite", () => {
    const inv = invitation({ stage: 'EVALUE', evaluated_at: new Date(Date.now() - 2 * JOUR).toISOString() });
    expect(composant.repereTemps(inv)).toBe('Évalué il y a 2 jours');
  });

  it("dit jusqu'à quand le candidat peut répondre", () => {
    const inv = invitation({ stage: 'EN_ATTENTE', expires_at: new Date(Date.now() + 2 * JOUR + 5 * MINUTE).toISOString() });
    expect(composant.repereTemps(inv)).toBe('Réponse sous 2 j');
  });

  it("résume un candidat absent en une phrase", () => {
    const inv = invitation({ stage: 'ABSENT', status: 'EXPIRED', created_at: new Date(Date.now() - 3 * JOUR).toISOString() });
    expect(composant.repereTemps(inv)).toBe('Sans réponse · envoyée il y a 3 jours');
  });

  it("dit depuis quand un entretien est annulé", () => {
    const inv = invitation({ stage: 'ANNULE', status: 'CANCELLED', cancelled_at: new Date(Date.now() - JOUR).toISOString() });
    expect(composant.repereTemps(inv)).toBe('Annulé hier');
  });

  it("ne montre l'année de la tuile que si ce n'est pas l'année en cours", () => {
    const cetteAnnee = new Date(new Date().getFullYear(), 5, 15, 10).toISOString();
    const autreAnnee = new Date(new Date().getFullYear() - 1, 5, 15, 10).toISOString();
    expect(composant.moisTuile(cetteAnnee)).toBe('juin');
    expect(composant.moisTuile(autreAnnee)).toBe(`juin ${new Date().getFullYear() - 1}`);
  });

  it("un rendez-vous existe pour les étapes confirmées seulement", () => {
    expect(composant.aUnRendezVous(invitation({ stage: 'A_VENIR' }))).toBeTrue();
    expect(composant.aUnRendezVous(invitation({ stage: 'EVALUE' }))).toBeTrue();
    expect(composant.aUnRendezVous(invitation({ stage: 'EN_ATTENTE' }))).toBeFalse();
    expect(composant.aUnRendezVous(invitation({ stage: 'ANNULE' }))).toBeFalse();
  });
});


/**
 * Pagination par quatre, et tri. « Proche » se mesure à aujourd'hui : un
 * entretien à venir du plus imminent au plus lointain, un entretien passé du
 * plus récent au plus ancien.
 */
describe('InterviewManagerComponent — tri et pagination', () => {
  let composant: InterviewManagerComponent;
  const JOUR = 24 * 60 * MINUTE;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewManagerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    composant = TestBed.createComponent(InterviewManagerComponent).componentInstance;
  });

  function charger(liste: InvitationResponse[]) {
    composant.invitations = liste;
    composant.computeKpis();
    composant.rebuild();
  }

  const aVenir = (id: string, dansJours: number, nom = 'Candidat') =>
    invitation({ id, stage: 'A_VENIR', candidate_name: nom, slots: creneau(Date.now() + dansJours * JOUR) });
  const ids = () => composant.filtered.map(i => i.id);

  it('trie par défaut du plus proche au plus lointain', () => {
    expect(composant.tri).toBe('PROCHE');
    charger([aVenir('loin', 9), aVenir('proche', 1), aVenir('milieu', 4)]);
    expect(ids()).toEqual(['proche', 'milieu', 'loin']);
  });

  it('peut trier du plus éloigné au plus proche', () => {
    charger([aVenir('loin', 9), aVenir('proche', 1), aVenir('milieu', 4)]);
    composant.changerTri('ELOIGNE');
    expect(ids()).toEqual(['loin', 'milieu', 'proche']);
  });

  it('pour les entretiens passés, « proche » veut dire le plus récent', () => {
    charger([
      invitation({ id: 'ancien', stage: 'A_EVALUER', can_evaluate: true, slots: creneau(Date.now() - 9 * JOUR) }),
      invitation({ id: 'recent', stage: 'A_EVALUER', can_evaluate: true, slots: creneau(Date.now() - 1 * JOUR) }),
    ]);
    composant.selectTab('PASSES');
    expect(ids()).toEqual(['recent', 'ancien']);
    composant.changerTri('ELOIGNE');
    expect(ids()).toEqual(['ancien', 'recent']);   // les plus en retard d'abord
  });

  it('trie par nom, sans tenir compte des accents ni de la casse', () => {
    charger([aVenir('c', 1, 'Zied'), aVenir('a', 2, 'émilie'), aVenir('b', 3, 'Anis')]);
    composant.changerTri('NOM');
    expect(ids()).toEqual(['b', 'a', 'c']);   // Anis, émilie, Zied
  });

  it('départage deux entretiens à la même date par ordre alphabétique', () => {
    const debut = Date.now() + 2 * JOUR;
    charger([
      invitation({ id: 'z', stage: 'A_VENIR', candidate_name: 'Zied', slots: creneau(debut) }),
      invitation({ id: 'a', stage: 'A_VENIR', candidate_name: 'Anis', slots: creneau(debut) }),
    ]);
    expect(ids()).toEqual(['a', 'z']);
  });

  it("classe une invitation en attente selon son premier créneau proposé", () => {
    const creneaux = (jours: number[]) => jours.map((j, k) => ({
      id: `s${k}`, invitation_id: 'x', is_selected: false,
      start_at: new Date(Date.now() + j * JOUR).toISOString(),
      end_at: new Date(Date.now() + j * JOUR + 30 * MINUTE).toISOString(),
    }));
    charger([
      invitation({ id: 'tard', stage: 'EN_ATTENTE', status: 'PENDING', slots: creneaux([6, 8]) }),
      invitation({ id: 'tot', stage: 'EN_ATTENTE', status: 'PENDING', slots: creneaux([9, 2]) }),
    ]);
    composant.selectTab('EN_ATTENTE');
    expect(ids()).toEqual(['tot', 'tard']);
  });

  it('affiche quatre cartes par page', () => {
    charger(Array.from({ length: 9 }, (_, k) => aVenir(`i${k}`, k + 1)));
    expect(composant.pageSize).toBe(4);
    expect(composant.totalPages).toBe(3);
    expect(composant.pagedFiltered.length).toBe(4);
    composant.nextPage(); composant.nextPage();
    expect(composant.pagedFiltered.length).toBe(1);
    expect([composant.plageDebut, composant.plageFin]).toEqual([9, 9]);
    expect(composant.plageTexte).toBe('9 sur 9');
  });

  it('la plage affichée suit la page courante', () => {
    charger(Array.from({ length: 9 }, (_, k) => aVenir(`i${k}`, k + 1)));
    expect([composant.plageDebut, composant.plageFin]).toEqual([1, 4]);
    expect(composant.plageTexte).toBe('1–4 sur 9');
    composant.nextPage();
    expect([composant.plageDebut, composant.plageFin]).toEqual([5, 8]);
  });

  it("une liste vide n'annonce aucune plage", () => {
    charger([]);
    expect([composant.plageDebut, composant.plageFin]).toEqual([0, 0]);
  });

  it("changer de tri ou d'onglet ramène à la première page", () => {
    charger(Array.from({ length: 9 }, (_, k) => aVenir(`i${k}`, k + 1)));
    composant.nextPage();
    composant.changerTri('NOM');
    expect(composant.currentPage).toBe(1);

    composant.nextPage();
    composant.selectTab('A_VENIR');
    expect(composant.currentPage).toBe(1);
  });
});
