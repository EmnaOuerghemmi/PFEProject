import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { InterviewEvaluationComponent } from './interview-evaluation.component';
import { InterviewSuggestion } from '../../../core/services/assessment.service';

/**
 * Proposition d'évaluation : seuls les critères NOTÉS s'affichent, sous la
 * forme « Communication 75 », sans justification. Un critère sans note
 * (« — ») n'apporte rien au recruteur et n'apparaît pas.
 */
describe("InterviewEvaluationComponent — proposition d'évaluation", () => {
  let fixture: ComponentFixture<InterviewEvaluationComponent>;
  let composant: InterviewEvaluationComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewEvaluationComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    fixture = TestBed.createComponent(InterviewEvaluationComponent);
    composant = fixture.componentInstance;
    composant.applicationId = 'app-1';
    composant.suggestion = {
      available: true,
      overall: 75,
      summary: 'Bonne communication.',
      criteria: {
        communication: { score: 75, justification: 'Présentation claire.' },
        technique: { score: null, justification: 'Non abordé dans les notes.' },
        adequation: { score: 80, justification: 'Contexte produit.' },
        motivation: { score: 70, justification: 'Projet clair.' },
      },
    } as InterviewSuggestion;
    fixture.detectChanges();
  });

  it('ne liste que les critères notés', () => {
    expect(composant.clesCriteres).toEqual(['communication', 'adequation', 'motivation']);
  });

  it('affiche le critère et sa note, sans justification ni « — »', () => {
    const lignes = Array.from(fixture.nativeElement.querySelectorAll('.ie-criteres li'))
      .map(li => (li as HTMLElement).textContent!.replace(/\s+/g, ' ').trim());

    expect(lignes.length).toBe(3);
    expect(lignes[0]).toMatch(/^Communication.*75$/);
    expect(fixture.nativeElement.querySelector('.ie-criteres').textContent).not.toContain('Présentation claire');
    expect(fixture.nativeElement.querySelector('.ie-criteres').textContent).not.toContain('—');
  });
});
