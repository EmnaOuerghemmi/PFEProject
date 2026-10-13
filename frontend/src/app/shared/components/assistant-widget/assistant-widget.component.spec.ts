import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';

import { AssistantWidgetComponent } from './assistant-widget.component';
import { AssistantReponse } from '../../../core/services/cag.service';

function reponse(over: Partial<AssistantReponse> = {}): AssistantReponse {
  return {
    reponse: 'Classement pour « Ingénieur Data » (2 candidat(s)).',
    elements: [{ libelle: '#1 Yasmine Belhadj', detail: 'Recruter · 88/100', lien: '/admin/decision',
                 parametres: { offre: 'o-1', candidature: 'a-1' } }],
    suggestions: ['Entretiens pour Ingénieur Data'],
    contexte: { outil: 'classement', offre_id: 'o-1' },
    sources: [],
    confiance: null,
    ...over,
  };
}

/**
 * Assistant connecté aux données : chaque message part vers
 * `/assistant/message` avec le contexte de la réponse précédente (relances),
 * les résultats mènent à leur page, et les relances ne s'affichent que sous
 * la dernière réponse.
 */
describe('AssistantWidgetComponent — assistant connecté aux données', () => {
  let fixture: ComponentFixture<AssistantWidgetComponent>;
  let composant: AssistantWidgetComponent;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AssistantWidgetComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(AssistantWidgetComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    composant.open = true;
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('accueille avec des questions cliquables', () => {
    const relances = fixture.nativeElement.querySelectorAll('.aw-relances .aw-chip');
    expect(relances.length).toBeGreaterThan(0);
  });

  it('envoie le message, puis rappelle le contexte au message suivant', () => {
    composant.ask('Meilleurs candidats pour ingenieur data');
    const premier = http.expectOne(r => r.url.endsWith('assistant/message'));
    expect(premier.request.body).toEqual({ message: 'Meilleurs candidats pour ingenieur data', contexte: null });
    premier.flush(reponse());

    composant.ask('et les entretiens ?');
    const second = http.expectOne(r => r.url.endsWith('assistant/message'));
    expect(second.request.body.contexte).toEqual({ outil: 'classement', offre_id: 'o-1' });
    second.flush(reponse({ elements: [], suggestions: [] }));
  });

  it('affiche les résultats, qui ouvrent leur page', () => {
    const router = TestBed.inject(Router);
    const navigation = spyOn(router, 'navigate').and.resolveTo(true);

    composant.ask('Meilleurs candidats');
    http.expectOne(r => r.url.endsWith('assistant/message')).flush(reponse());
    fixture.detectChanges();

    const ligne = fixture.nativeElement.querySelector('.aw-item') as HTMLButtonElement;
    expect(ligne.textContent).toContain('#1 Yasmine Belhadj');
    ligne.click();
    expect(navigation).toHaveBeenCalledWith(['/admin/decision'], { queryParams: { offre: 'o-1', candidature: 'a-1' } });
  });

  it('ne montre les relances que sous la dernière réponse', () => {
    composant.ask('Meilleurs candidats');
    http.expectOne(r => r.url.endsWith('assistant/message')).flush(reponse());
    fixture.detectChanges();

    const blocs = fixture.nativeElement.querySelectorAll('.aw-relances');
    expect(blocs.length).toBe(1);
    expect((blocs[0] as HTMLElement).textContent).toContain('Entretiens pour Ingénieur Data');
  });

  it('une erreur réseau donne un message, sans bloquer la saisie', () => {
    composant.ask('bonjour');
    http.expectOne(r => r.url.endsWith('assistant/message'))
      .flush({}, { status: 500, statusText: 'Server Error' });

    expect(composant.asking).toBeFalse();
    expect(composant.messages[composant.messages.length - 1].text).toContain('Une erreur est survenue');
  });
});
