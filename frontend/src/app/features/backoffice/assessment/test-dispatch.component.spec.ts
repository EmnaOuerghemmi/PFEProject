import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { AssessmentService, TestQuestion } from '../../../core/services/assessment.service';
import { TestDispatchComponent } from './test-dispatch.component';

/**
 * Les compteurs de l'écran « 30 → 12 ».
 *
 * Ils sont recalculés côté client à chaque clic, et c'est sur eux que le RH
 * décide d'envoyer ou non. S'ils mentent, un test part en ne mesurant qu'une
 * technologie sur quatre sans que personne ne le voie — d'où ces tests.
 */
function question(over: Partial<TestQuestion>): TestQuestion {
  return {
    id: over.id || Math.random().toString(36).slice(2),
    job_offer_id: 'job-1',
    statement: 'Une question du vivier ?',
    options: ['A', 'B', 'C', 'D'],
    correct_answer: ['B'],
    explanation: null,
    difficulty: 'MOYENNE',
    kind: 'QCM_UNIQUE',
    status: 'ACTIVE',
    expected_seconds: 90,
    skill_tag: null,
    generated_by: null,
    times_served: 0,
    times_correct: 0,
    times_skipped: 0,
    success_rate: null,
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('TestDispatchComponent — compteurs de couverture', () => {
  let composant: TestDispatchComponent;
  let service: jasmine.SpyObj<AssessmentService>;

  const vivier = [
    question({ id: 'q1', difficulty: 'FACILE',    skill_tag: 'angular' }),
    question({ id: 'q2', difficulty: 'MOYENNE',   skill_tag: 'java' }),
    question({ id: 'q3', difficulty: 'DIFFICILE', skill_tag: 'sql' }),
    question({ id: 'q4', difficulty: 'FACILE',    skill_tag: 'angular' }),
    question({ id: 'q5', difficulty: 'MOYENNE',   skill_tag: null }),
  ];

  beforeEach(() => {
    service = jasmine.createSpyObj('AssessmentService',
      ['listQuestions', 'prepareTest', 'sendTest']);

    TestBed.configureTestingModule({
      imports: [TestDispatchComponent],
      providers: [{ provide: AssessmentService, useValue: service }],
    });

    composant = TestBed.createComponent(TestDispatchComponent).componentInstance;
    composant.applicationId = 'app-1';
    composant.jobId = 'job-1';
    composant.requiredSkills = ['Angular', 'Java', 'SQL', 'Docker'];
    composant.vivier = vivier;
  });

  it('ne compte comme couverte qu\'une compétence réellement représentée', () => {
    composant.retenues = new Set(['q1', 'q2']);

    // La casse de l'offre (« Angular ») et celle du tag (« angular ») diffèrent :
    // les comparer telles quelles ferait passer une offre pour non couverte.
    expect(composant.competencesCouvertes).toEqual(['Angular', 'Java']);
    expect(composant.competencesManquantes).toEqual(['SQL', 'Docker']);
  });

  it('ne fait pas passer une question non rattachée pour une couverture', () => {
    composant.retenues = new Set(['q5']);
    expect(composant.competencesCouvertes).toEqual([]);
    expect(composant.competencesManquantes.length).toBe(4);
  });

  it('compte les difficultés de la sélection, pas du vivier', () => {
    composant.retenues = new Set(['q1', 'q4', 'q2']);
    expect(composant.compteDifficulte('FACILE')).toBe(2);
    expect(composant.compteDifficulte('MOYENNE')).toBe(1);
    expect(composant.compteDifficulte('DIFFICILE')).toBe(0);
    expect(composant.total).toBe(3);
  });

  it('déduit la durée conseillée du temps attendu des questions retenues', () => {
    composant.retenues = new Set(['q1', 'q2', 'q3', 'q4', 'q5']);   // 5 × 90 s
    expect(composant.dureeConseillee).toBe(8);                      // arrondi au-dessus

    composant.dureeMinutes = 5;
    expect(composant.dureeTropCourte).toBeTrue();
    composant.dureeMinutes = 20;
    expect(composant.dureeTropCourte).toBeFalse();
  });

  it('ne conseille jamais moins que le minimum accepté par l API', () => {
    composant.retenues = new Set(['q1', 'q2']);          // 180 s, soit 3 min
    expect(composant.dureeConseillee).toBe(5);
  });

  it('ne signale pas une durée trop courte quand rien n\'est retenu', () => {
    composant.retenues = new Set();
    composant.dureeMinutes = 5;
    expect(composant.dureeTropCourte).toBeFalse();
    expect(composant.peutEnvoyer).toBeFalse();
  });

  it('bascule une question sans toucher aux autres', () => {
    composant.retenues = new Set(['q1']);
    composant.basculer(vivier[1]);
    expect(composant.estRetenue(vivier[0])).toBeTrue();
    expect(composant.estRetenue(vivier[1])).toBeTrue();
    composant.basculer(vivier[0]);
    expect(composant.estRetenue(vivier[0])).toBeFalse();
  });

  it('laisse choisir à la main si la présélection du serveur échoue', () => {
    service.listQuestions.and.returnValue(of(vivier));
    service.prepareTest.and.returnValue(throwError(() => ({ status: 500 })));

    composant.charger();

    // Le vivier reste utilisable : c'est tout l'enjeu du repli.
    expect(composant.vivier.length).toBe(5);
    expect(composant.retenues.size).toBe(0);
    expect(composant.erreur).toContain('à la main');
  });

  it('n\'envoie que les questions retenues, avec la durée saisie', () => {
    service.sendTest.and.returnValue(of({}));
    composant.retenues = new Set(['q3', 'q1']);
    composant.dureeMinutes = 25;

    composant.envoyer();

    const [appId, ids, duree] = service.sendTest.calls.mostRecent().args;
    expect(appId).toBe('app-1');
    expect(ids.sort()).toEqual(['q1', 'q3']);
    expect(duree).toBe(25);
  });
});
