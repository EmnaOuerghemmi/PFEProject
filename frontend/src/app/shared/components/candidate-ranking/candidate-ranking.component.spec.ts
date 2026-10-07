import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { CandidateRankingComponent } from './candidate-ranking.component';

/**
 * Parcours critique n°3 — affichage du classement IA.
 *
 * C'est sur cet écran que se prennent les décisions de recrutement. Deux
 * risques sont couverts ici : afficher un candidat sous le mauvais palier de
 * score — donc proposer la mauvaise action — et permettre de planifier un
 * entretien déjà confirmé, ce qui enverrait une seconde invitation au
 * candidat.
 */
describe('CandidateRankingComponent — classement IA', () => {
  let component: CandidateRankingComponent;
  let fixture: ComponentFixture<CandidateRankingComponent>;
  let http: HttpTestingController;

  function candidat(surcharges: Partial<any> = {}) {
    return {
      candidate_id: 'c1',
      candidate_name: 'Rim Chaabane',
      application_id: 'a1',
      total_score: 90,
      rank: 1,
      skills_score: 90,
      experience_score: 90,
      education_score: 90,
      score_details: null,
      interview_status: null,
      ...surcharges,
    };
  }

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [CandidateRankingComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(CandidateRankingComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  // ── Paliers de score ─────────────────────────────────────────────────────

  it('classe les scores dans le bon palier', () => {
    // Les seuils pilotent l'action proposée au recruteur : 85 déclenche la
    // négociation directe, sous 30 c'est le rejet qui est proposé.
    expect(component.getScoreClass(95)).toBe('excellent');
    expect(component.getScoreClass(85)).toBe('excellent');
    expect(component.getScoreClass(84)).toBe('good');
    expect(component.getScoreClass(60)).toBe('good');
    expect(component.getScoreClass(59)).toBe('average');
    expect(component.getScoreClass(30)).toBe('average');
    expect(component.getScoreClass(29)).toBe('poor');
    expect(component.getScoreClass(0)).toBe('poor');
  });

  it('associe un libelle a chaque palier', () => {
    expect(component.getScoreLabel(90)).toContain('Excellent');
    expect(component.getScoreLabel(70)).toContain('Bon');
    expect(component.getScoreLabel(40)).toContain('Moyen');
    expect(component.getScoreLabel(10)).toContain('Faible');
  });

  // ── Chargement ───────────────────────────────────────────────────────────

  it('charge le classement de l offre fournie', () => {
    component.jobId = 'job-7';
    fixture.detectChanges();

    const requete = http.expectOne(r => r.url.includes('/jobs/job-7/ranking'));
    requete.flush({ job_offer_id: 'job-7', total_candidates: 1, ranking: [candidat()] });

    expect(component.candidates.length).toBe(1);
    expect(component.candidates[0].candidate_name).toBe('Rim Chaabane');
    expect(component.isLoading).toBeFalse();
  });

  it('n interroge pas le serveur sans identifiant d offre', () => {
    component.jobId = '';
    fixture.detectChanges();

    http.expectNone(r => r.url.includes('/ranking'));
    expect(component.isLoading).toBeFalse();
  });

  it('sort de l etat de chargement meme en cas d erreur', () => {
    // Sinon l'écran resterait bloqué sur un spinner perpétuel.
    component.jobId = 'job-7';
    fixture.detectChanges();

    http.expectOne(r => r.url.includes('/ranking')).flush(
      { detail: 'boom' }, { status: 500, statusText: 'Server Error' },
    );

    expect(component.isLoading).toBeFalse();
    expect(component.candidates).toEqual([]);
  });

  // ── État des entretiens ──────────────────────────────────────────────────

  it('reconnait un entretien confirme', () => {
    const c = candidat({ interview_status: 'CONFIRMED' }) as any;

    expect(component.hasActiveInterview(c)).toBeTrue();
    expect(component.isInterviewConfirmed(c)).toBeTrue();
    expect(component.isInterviewPending(c)).toBeFalse();
    expect(component.interviewBadgeLabel(c)).toContain('confirmé');
  });

  it('reconnait une invitation en attente', () => {
    const c = candidat({ interview_status: 'PENDING' }) as any;

    expect(component.hasActiveInterview(c)).toBeTrue();
    expect(component.isInterviewPending(c)).toBeTrue();
    expect(component.interviewBadgeLabel(c)).toContain('envoyée');
  });

  it('considere qu il n y a pas d entretien sans statut', () => {
    const c = candidat({ interview_status: null }) as any;

    expect(component.hasActiveInterview(c)).toBeFalse();
    expect(component.interviewBadgeLabel(c)).toBe('');
  });

  it('bloque une seconde planification si un entretien est deja actif', () => {
    // Garde-fou métier : sans lui, un double clic enverrait deux invitations
    // au même candidat.
    const emis: any[] = [];
    component.scheduleInterview.subscribe(a => emis.push(a));

    component.onScheduleInterview(candidat({ interview_status: 'CONFIRMED' }) as any);
    expect(emis.length).toBe(0);

    component.onScheduleInterview(candidat({ interview_status: null }) as any);
    expect(emis.length).toBe(1);
    expect(emis[0].applicationId).toBe('a1');
  });

  // ── Second entretien ─────────────────────────────────────────────────────

  it('un entretien confirmé qui a eu lieu ne retient plus le bouton', () => {
    const c = candidat({ interview_status: 'CONFIRMED', interview_ended: true }) as any;

    expect(component.hasActiveInterview(c)).toBeFalse();
    expect(component.isInterviewConfirmed(c)).toBeFalse();
    expect(component.isInterviewPassed(c)).toBeTrue();
    expect(component.interviewBadgeLabel(c)).toContain('passé');
  });

  it('permet de planifier un nouvel entretien une fois le premier passé', () => {
    const emis: any[] = [];
    component.scheduleInterview.subscribe(a => emis.push(a));

    component.onScheduleInterview(candidat({ interview_status: 'CONFIRMED', interview_ended: true }) as any);

    expect(emis.length).toBe(1);
  });

  it('un entretien confirmé à venir garde le bouton bloqué', () => {
    const emis: any[] = [];
    component.scheduleInterview.subscribe(a => emis.push(a));
    const c = candidat({ interview_status: 'CONFIRMED', interview_ended: false }) as any;

    component.onScheduleInterview(c);

    expect(component.hasActiveInterview(c)).toBeTrue();
    expect(emis.length).toBe(0);
  });

  it('une invitation en attente bloque toujours, même si un entretien est déjà passé', () => {
    // Après le premier entretien, le RH a envoyé une nouvelle invitation : le
    // classement renvoie celle-là, et un second envoi doublerait la demande.
    const c = candidat({ interview_status: 'PENDING', interview_ended: false }) as any;
    expect(component.hasActiveInterview(c)).toBeTrue();
  });

  it('transmet le score dans les actions de workflow', () => {
    const rejets: any[] = [];
    component.rejectCandidate.subscribe(a => rejets.push(a));

    component.onReject(candidat({ total_score: 22 }) as any);

    expect(rejets.length).toBe(1);
    expect(rejets[0].score).toBe(22);
    expect(rejets[0].candidateId).toBe('c1');
  });

  // ── Repli d'affichage ────────────────────────────────────────────────────

  it('affiche le nom du candidat quand il est fourni', () => {
    component.jobId = 'job-7';
    fixture.detectChanges();
    http.expectOne(r => r.url.includes('/ranking')).flush({
      job_offer_id: 'job-7', total_candidates: 1, ranking: [candidat()],
    });
    fixture.detectChanges();

    const texte = (fixture.nativeElement as HTMLElement).textContent || '';
    expect(texte).toContain('Rim Chaabane');
  });

  it('se rabat sur l identifiant quand le nom est absent', () => {
    // Le backend ne renvoie candidate_name que depuis l'ajout de la jointure
    // Candidate : l'affichage doit rester lisible sur d'anciennes données.
    component.jobId = 'job-7';
    fixture.detectChanges();
    http.expectOne(r => r.url.includes('/ranking')).flush({
      job_offer_id: 'job-7',
      total_candidates: 1,
      ranking: [candidat({ candidate_name: undefined, candidate_id: 'abcdef123456789' })],
    });
    fixture.detectChanges();

    const texte = (fixture.nativeElement as HTMLElement).textContent || '';
    expect(texte).toContain('abcdef123456');
  });
});
