import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { HiringRecommendation } from '../../../core/services/report.service';
import { DecisionComponent } from './decision.component';

/**
 * La recommandation peut devenir le statut de la candidature.
 *
 * Recruter → Acceptée, Rejeter → Rejetée, En réserve → En réserve. « À
 * confirmer » ne change aucun statut : il demande une étape de plus.
 */
function candidat(over: Partial<HiringRecommendation> = {}): HiringRecommendation {
  return {
    application_id: 'app-1',
    candidate_id: 'cand-1',
    candidate_name: 'Candidat Test',
    decision_rank: 1,
    recommendation: 'HOLD',
    confidence: 'medium',
    rationale: '',
    strengths: [],
    warnings: [],
    next_step: '',
    composite: { score: 70, completeness: 3, available: [], missing: [], band: 'good' },
    cv: { score: 80, skills_score: 80, experience_score: 80, education_score: 80, matched_skills: 3, missing_skills: 0 },
    test: { status: null, score: null, hard_success_rate: null, hard_total: 0, anomaly_count: 0, overrun_questions: 0 },
    interview: { score: null, status: null, has_notes: false },
    expected_salary: null,
    tie: null,
    total_score: 80,
    application_status: 'INTERVIEW_SCHEDULED',
    ...over,
  } as HiringRecommendation;
}

describe('DecisionComponent — appliquer la recommandation', () => {
  let composant: DecisionComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [DecisionComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    composant = TestBed.createComponent(DecisionComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  it('propose d appliquer une recommandation qui change le statut', () => {
    expect(composant.etatApplication(candidat({ recommendation: 'HOLD' }))).toBe('possible');
    expect(composant.etatApplication(candidat({ recommendation: 'HIRE' }))).toBe('possible');
    expect(composant.etatApplication(candidat({ recommendation: 'REJECT' }))).toBe('possible');
  });

  it('sans les trois notes, pas de score global et un lien vers l étape qui manque', () => {
    const cvSeul = candidat({
      recommendation: 'INCOMPLETE',
      composite: { score: 83.3, completeness: 1, available: ['cv'], missing: ['interview', 'test'], band: 'good' },
    });
    expect(composant.scoreComplet(cvSeul)).toBeFalse();
    expect(composant.etapeManquante(cvSeul)).toEqual({ libelle: 'Envoyer le test', lien: '/admin/assessment' });

    const sansEntretien = candidat({
      recommendation: 'INCOMPLETE',
      composite: { score: 80, completeness: 2, available: ['cv', 'test'], missing: ['interview'], band: 'good' },
    });
    expect(composant.etapeManquante(sansEntretien)).toEqual({ libelle: 'Planifier un entretien', lien: '/admin/interviews' });

    // L'étape suit l'état réel : un test déjà envoyé se suit, il ne se renvoie pas.
    const testEnvoye = candidat({
      recommendation: 'INCOMPLETE',
      composite: { score: 70, completeness: 1, available: ['cv'], missing: ['interview', 'test'], band: 'good' },
      test: { status: 'ENVOYE', score: null, hard_success_rate: null, hard_total: 0, anomaly_count: 0, overrun_questions: 0 },
    });
    expect(composant.etapeManquante(testEnvoye).libelle).toBe('Suivre le test');
    const entretienPrevu = candidat({
      recommendation: 'INCOMPLETE',
      composite: { score: 80, completeness: 2, available: ['cv', 'test'], missing: ['interview'], band: 'good' },
      interview: { score: null, status: 'CONFIRMED', has_notes: false },
    });
    expect(composant.etapeManquante(entretienPrevu).libelle).toBe("Voir l'entretien prévu");

    expect(composant.scoreComplet(candidat({
      composite: { score: 84, completeness: 3, available: ['cv', 'interview', 'test'], missing: [], band: 'good' },
    }))).toBeTrue();
  });

  it('« Évaluation en cours » n a rien à appliquer', () => {
    expect(composant.etatApplication(candidat({ recommendation: 'INCOMPLETE' }))).toBe('sans-objet');
  });

  it('dit quand la recommandation est déjà le statut', () => {
    expect(composant.etatApplication(candidat({ recommendation: 'HOLD', application_status: 'ON_HOLD' }))).toBe('appliquee');
  });

  it('refuse de reculer d Acceptée à En réserve', () => {
    expect(composant.etatApplication(candidat({ recommendation: 'HOLD', application_status: 'ACCEPTED' }))).toBe('impossible');
  });

  it('affiche le libellé et la couleur du statut actuel', () => {
    expect(composant.statutLabel('ON_HOLD')).toBe('En réserve');
    expect(composant.statutLabel(null)).toBe('—');
    expect(composant.statutCouleur('INCONNU')).toBe('#7C8A8A');
  });

  it('filtre et compte par recommandation', () => {
    composant.candidates = [
      candidat({ application_id: 'a', recommendation: 'HIRE' }),
      candidat({ application_id: 'b', recommendation: 'HOLD' }),
      candidat({ application_id: 'c', recommendation: 'HOLD' }),
    ];
    expect(composant.compte('TOUS')).toBe(3);
    expect(composant.compte('HOLD')).toBe(2);
    composant.filtre = 'HOLD';
    expect(composant.candidatsAffiches.map(c => c.application_id)).toEqual(['b', 'c']);
  });

  it('envoie la décision, puis met à jour le statut affiché', () => {
    const c = candidat({ recommendation: 'HOLD' });
    composant.demanderApplication(c);
    composant.confirmerApplication();

    const req = http.expectOne(r => r.url.endsWith('/decision/applications/app-1/apply'));
    expect(req.request.body).toEqual({ decision: 'HOLD', message: '' });
    req.flush({ application_id: 'app-1', application_status: 'ON_HOLD', email_sent: true });

    expect(c.application_status).toBe('ON_HOLD');
    expect(composant.aConfirmer).toBeNull();
    expect(composant.succes).toContain('e-mail');
  });

  it('transmet le mot du RH avec un refus seulement', () => {
    const c = candidat({ recommendation: 'REJECT' });
    composant.demanderApplication(c);
    composant.messageRefus = '  Bonne continuation  ';
    composant.confirmerApplication();

    const req = http.expectOne(r => r.url.endsWith('/apply'));
    expect(req.request.body).toEqual({ decision: 'REJECT', message: 'Bonne continuation' });
  });

  it('garde la fenêtre ouverte et dit pourquoi en cas de refus du serveur', () => {
    const c = candidat({ recommendation: 'HIRE' });
    composant.demanderApplication(c);
    composant.confirmerApplication();

    http.expectOne(r => r.url.endsWith('/apply'))
      .flush({ detail: 'Passage impossible.' }, { status: 409, statusText: 'Conflict' });

    expect(composant.aConfirmer).toBe(c);
    expect(composant.erreurApplication).toBe('Passage impossible.');
    expect(c.application_status).toBe('INTERVIEW_SCHEDULED');
  });
});
