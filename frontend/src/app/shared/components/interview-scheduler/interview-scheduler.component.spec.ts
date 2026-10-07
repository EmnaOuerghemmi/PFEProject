import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { of } from 'rxjs';

import {
  Application,
  JobOffer,
  PaginatedJobs,
  RecruitmentService,
} from '../../../core/services/recruitment.service';
import { UserService } from '../../../core/services/user.service';
import { InterviewSchedulerComponent } from './interview-scheduler.component';

function offre(id: string, titre: string, statut = 'PUBLISHED'): JobOffer {
  return { id, title: titre, status: statut } as unknown as JobOffer;
}

function candidature(id: string, nom: string, statut: string): Application {
  return { id, candidate_name: nom, status: statut } as unknown as Application;
}

function page(items: JobOffer[], numero: number, taille: number, total: number): PaginatedJobs {
  return { items, page: numero, size: taille, total } as PaginatedJobs;
}

/**
 * Création d'un entretien depuis la page des entretiens : on choisit l'offre,
 * puis un candidat DE CETTE OFFRE.
 *
 * Ce qui compte ici : aucune offre ni aucun candidat ne disparaît en silence
 * (l'API plafonne ses pages), un dossier clos n'est pas proposé, et les écrans
 * qui planifient depuis une candidature déjà ouverte ne changent pas.
 */
describe('InterviewSchedulerComponent — choix de l\'offre puis du candidat', () => {
  let fixture: ComponentFixture<InterviewSchedulerComponent>;
  let composant: InterviewSchedulerComponent;
  let recrutement: RecruitmentService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewSchedulerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    recrutement = TestBed.inject(RecruitmentService);
    spyOn(TestBed.inject(UserService), 'listUsers').and.returnValue(of({ items: [] } as any));
    fixture = TestBed.createComponent(InterviewSchedulerComponent);
    composant = fixture.componentInstance;
  });

  function ouvrirEnModeSelection(): void {
    fixture.componentRef.setInput('selectionCandidat', true);
    fixture.detectChanges();
  }

  // ── Offres ──────────────────────────────────────────────────────────────

  it('n\'affiche rien de plus quand l\'écran impose la candidature', () => {
    const offres = spyOn(recrutement, 'getJobsForManagement');
    fixture.componentRef.setInput('applicationId', 'app-42');
    fixture.detectChanges();

    expect(offres).not.toHaveBeenCalled();
    expect(composant.cibleId).toBe('app-42');
    expect(fixture.nativeElement.querySelector('.target-section')).toBeNull();
  });

  it('écarte les brouillons : personne n\'y a encore postulé', () => {
    spyOn(recrutement, 'getJobsForManagement').and.returnValue(of(page(
      [offre('o1', 'Dev Angular'), offre('o2', 'Brouillon', 'DRAFT')], 1, 100, 2)));
    ouvrirEnModeSelection();

    expect(composant.offreOptions.map(o => o.value)).toEqual(['o1']);
  });

  it('indique le statut d\'une offre qui n\'est plus publiée', () => {
    spyOn(recrutement, 'getJobsForManagement').and.returnValue(of(page(
      [offre('o1', 'Dev Angular', 'CLOSED')], 1, 100, 1)));
    ouvrirEnModeSelection();

    expect(composant.offreOptions[0].label).toBe('Dev Angular (Fermée)');
  });

  it('lit toutes les pages d\'offres, pas seulement la première', () => {
    const lecture = spyOn(recrutement, 'getJobsForManagement').and.callFake((n: number) =>
      of(n === 1
        ? page([offre('o1', 'Première')], 1, 1, 2)
        : page([offre('o2', 'Seconde')], 2, 1, 2)));
    ouvrirEnModeSelection();

    expect(lecture).toHaveBeenCalledTimes(2);
    expect(composant.offreOptions.map(o => o.value)).toEqual(['o1', 'o2']);
  });

  // ── Candidats ───────────────────────────────────────────────────────────

  function avecOffres(): void {
    spyOn(recrutement, 'getJobsForManagement').and.returnValue(of(page([offre('o1', 'Dev')], 1, 100, 1)));
  }

  it('ne propose que les dossiers planifiables, sans afficher leur statut', () => {
    avecOffres();
    spyOn(recrutement, 'getApplications').and.returnValue(of([
      candidature('a1', 'Rejeté', 'REJECTED'),
      candidature('a2', 'En attente', 'PENDING'),
      candidature('a3', 'Recruté', 'HIRED'),
      candidature('a4', 'Test passé', 'TEST_DONE'),
    ]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');

    // Les libellés sont les noms seuls : le statut n'a pas à s'y afficher.
    expect(composant.candidatOptions).toEqual([
      { value: 'a2', label: 'En attente' },
      { value: 'a4', label: 'Test passé' },
    ]);
    expect(composant.nbNonPlanifiables).toBe(2);
  });

  it('un dossier déjà accepté n\'est pas proposé : ce serait un retour en arrière', () => {
    avecOffres();
    spyOn(recrutement, 'getApplications').and.returnValue(of([candidature('a1', 'Accepté', 'ACCEPTED')]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');

    expect(composant.candidatOptions).toEqual([]);
    expect(composant.nbNonPlanifiables).toBe(1);
  });

  it('un second entretien reste possible', () => {
    avecOffres();
    spyOn(recrutement, 'getApplications').and.returnValue(
      of([candidature('a1', 'Déjà vu une fois', 'INTERVIEW_SCHEDULED')]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');

    expect(composant.candidatOptions.map(c => c.value)).toEqual(['a1']);
  });

  it('lit toutes les candidatures d\'une offre, par pages de 100', () => {
    avecOffres();
    const pleine = Array.from({ length: 100 }, (_, i) => candidature(`p${i}`, `Candidat ${i}`, 'PENDING'));
    const lecture = spyOn(recrutement, 'getApplications').and.callFake(
      (_offre: string | undefined, n: number) => of(n === 1 ? pleine : [candidature('dernier', 'Dernier', 'PENDING')]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');

    expect(lecture).toHaveBeenCalledTimes(2);
    expect(composant.candidatOptions.length).toBe(101);
  });

  it('une page incomplète met fin à la lecture', () => {
    avecOffres();
    const lecture = spyOn(recrutement, 'getApplications').and.returnValue(of([candidature('a1', 'Seul', 'PENDING')]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');

    expect(lecture).toHaveBeenCalledTimes(1);
  });

  it('changer d\'offre efface le candidat déjà choisi', () => {
    avecOffres();
    spyOn(recrutement, 'getApplications').and.returnValue(of([candidature('a1', 'Alpha', 'PENDING')]));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');
    composant.candidatureId = 'a1';

    composant.choisirOffre('');

    expect(composant.candidatureId).toBe('');
    expect(composant.candidatOptions).toEqual([]);
  });

  // ── Envoi ───────────────────────────────────────────────────────────────

  it('refuse d\'envoyer tant qu\'aucun candidat n\'est choisi', () => {
    avecOffres();
    const envoi = spyOn(recrutement, 'scheduleInterview');
    ouvrirEnModeSelection();
    composant.slots = ['2026-12-01T10:00'];

    composant.submit();

    expect(envoi).not.toHaveBeenCalled();
    expect(composant.errorMsg).toContain('candidat');
  });

  it('invite la candidature choisie, pas une autre', () => {
    avecOffres();
    spyOn(recrutement, 'getApplications').and.returnValue(of([candidature('a1', 'Alpha', 'PENDING')]));
    const envoi = spyOn(recrutement, 'scheduleInterview').and.returnValue(of({ message: 'ok' }));
    ouvrirEnModeSelection();
    composant.choisirOffre('o1');
    composant.candidatureId = 'a1';
    composant.slots = ['2026-12-01T10:00'];

    composant.submit();

    expect(envoi).toHaveBeenCalledTimes(1);
    expect(envoi.calls.mostRecent().args[0]).toBe('a1');
  });
});

/**
 * Les membres de l'entretien : ceux qui le mènent, et seuls à pouvoir
 * l'évaluer. On en ajoute autant qu'il faut ; un membre ajouté quitte la
 * liste de choix, et y revient quand on le retire.
 */
describe("InterviewSchedulerComponent — membres de l'entretien", () => {
  let fixture: ComponentFixture<InterviewSchedulerComponent>;
  let composant: InterviewSchedulerComponent;
  let recrutement: RecruitmentService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewSchedulerComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    recrutement = TestBed.inject(RecruitmentService);
    spyOn(TestBed.inject(UserService), 'listUsers').and.returnValue(of({
      items: [
        { id: 'u1', role: 'RH', full_name: 'Sami Trabelsi', email: 'sami@piqbit.tn' },
        { id: 'u2', role: 'CANDIDAT', full_name: 'Une Candidate', email: 'candidate@exemple.tn' },
        { id: 'u3', role: 'RECRUTEUR', username: 'rec3', email: 'rec3@piqbit.tn' },
      ],
    } as any));
    fixture = TestBed.createComponent(InterviewSchedulerComponent);
    composant = fixture.componentInstance;
    fixture.componentRef.setInput('applicationId', 'app-1');
    fixture.detectChanges();
  });

  it("propose le personnel de recrutement seulement", () => {
    expect(composant.recruteurOptions).toEqual([
      { value: 'u1', label: 'Sami Trabelsi <sami@piqbit.tn>' },
      { value: 'u3', label: 'rec3 <rec3@piqbit.tn>' },
    ]);
  });

  it("un candidat n'est jamais proposé comme membre", () => {
    expect(composant.recruteurOptions.map(o => o.value)).not.toContain('u2');
  });

  it("un membre ajouté quitte la liste, et y revient une fois retiré", () => {
    composant.ajouterMembre('u1');
    expect(composant.membres.map(m => m.id)).toEqual(['u1']);
    expect(composant.recruteurOptions.map(o => o.value)).toEqual(['u3']);
    expect(composant.membreAAjouter).toBe('');

    composant.retirerMembre('u1');
    expect(composant.membres).toEqual([]);
    expect(composant.recruteurOptions.map(o => o.value)).toEqual(['u1', 'u3']);
  });

  it("n'ajoute pas deux fois le même membre", () => {
    composant.ajouterMembre('u3');
    composant.ajouterMembre('u3');
    expect(composant.membres.length).toBe(1);
  });

  it("transmet tous les membres choisis", () => {
    const envoi = spyOn(recrutement, 'scheduleInterview').and.returnValue(of({ message: 'ok' }));
    composant.slots = ['2026-12-01T10:00'];
    composant.ajouterMembre('u1');
    composant.ajouterMembre('u3');

    composant.submit();

    expect(envoi.calls.mostRecent().args[5]).toEqual(['u1', 'u3']);
  });

  it("sans membre, n'envoie aucun membre", () => {
    const envoi = spyOn(recrutement, 'scheduleInterview').and.returnValue(of({ message: 'ok' }));
    composant.slots = ['2026-12-01T10:00'];

    composant.submit();

    expect(envoi.calls.mostRecent().args[5]).toEqual([]);
  });
});
