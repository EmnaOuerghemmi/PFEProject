import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ApplyModalComponent } from './apply-modal.component';

/**
 * Parcours critique n°2 — candidature à une offre.
 *
 * C'est l'action qui fait vivre la plateforme : si le dépôt casse, plus aucune
 * candidature n'entre. Deux points appellent des tests plutôt qu'une relecture :
 *
 * * **L'ordre des deux étapes.** La candidature est créée dès l'envoi du CV,
 *   avant la question du salaire. Un candidat qui ferme la fenêtre à l'étape
 *   suivante a déjà postulé — c'est tout l'intérêt de cet ordre, et ce serait
 *   silencieusement perdu si quelqu'un le réinversait.
 * * **Les messages d'échec.** « Réessayez » est un mauvais conseil pour une
 *   session expirée comme pour un serveur injoignable.
 */
describe('ApplyModalComponent — dépôt de candidature', () => {
  let composant: ApplyModalComponent;
  let fixture: ComponentFixture<ApplyModalComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
      imports: [ApplyModalComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplyModalComponent);
    composant = fixture.componentInstance;
    composant.job = { id: 'job-1', salary_min: 1500, salary_max: 2200 } as any;
    http = TestBed.inject(HttpTestingController);

    fixture.detectChanges();                       // déclenche le chargement du CV
    http.expectOne((r) => r.url.includes('/cv')).flush({ has_cv: false });
  });

  afterEach(() => http.verify());

  function deposer(): void {
    composant.source = 'nouveau';
    composant.fichier = new File(['x'], 'cv.pdf', { type: 'application/pdf' });
  }

  // ── Validation du fichier ──────────────────────────────────────────────────

  function evenementFichier(nom: string, type: string, tailleOctets: number): Event {
    const fichier = new File(['x'], nom, { type });
    Object.defineProperty(fichier, 'size', { value: tailleOctets });
    return { target: { files: [fichier] } } as unknown as Event;
  }

  it('refuse un format non autorisé sans rien envoyer', () => {
    composant.surFichier(evenementFichier('photo.png', 'image/png', 1024));

    expect(composant.fichier).toBeNull();
    expect(composant.erreur).toContain('PDF');
    http.expectNone((r) => r.url.includes('/apply/'));
  });

  it('refuse un fichier de plus de 5 Mo', () => {
    composant.surFichier(evenementFichier('cv.pdf', 'application/pdf', 6 * 1024 * 1024));

    expect(composant.fichier).toBeNull();
    expect(composant.erreur).toContain('5 Mo');
  });

  it('n envoie rien tant qu aucun CV n est choisi', () => {
    composant.source = 'nouveau';
    composant.fichier = null;

    composant.envoyer();

    http.expectNone((r) => r.url.includes('/apply/'));
    expect(composant.envoi).toBeFalse();
  });

  // ── Envoi ──────────────────────────────────────────────────────────────────

  it('signale la candidature AVANT de demander le salaire', () => {
    const signale = jasmine.createSpy('applied');
    composant.applied.subscribe(signale);
    deposer();

    composant.envoyer();
    expect(composant.envoi).toBeTrue();
    http.expectOne((r) => r.url.includes('/apply/')).flush({ id: 'app-42' });

    expect(composant.envoi).toBeFalse();
    expect(signale).toHaveBeenCalled();
    expect(composant.etape).toBe('salaire');
    expect(composant.applicationId).toBe('app-42');
  });

  it('laisse passer la question du salaire sans perdre la candidature', () => {
    deposer();
    composant.envoyer();
    http.expectOne((r) => r.url.includes('/apply/')).flush({ id: 'app-42' });

    composant.passer();

    expect(composant.etape).toBe('termine');
    http.expectNone((r) => r.url.includes('expected-salary'));
  });

  it('termine quand même si l enregistrement du salaire échoue', () => {
    deposer();
    composant.envoyer();
    http.expectOne((r) => r.url.includes('/apply/')).flush({ id: 'app-42' });

    composant.pretention = 1800;
    composant.enregistrerPretention();
    http.expectOne((r) => r.url.includes('expected-salary'))
        .error(new ProgressEvent('error'), { status: 500, statusText: 'Server Error' });

    // L'étape est facultative : son échec ne doit pas laisser croire que la
    // candidature n'est pas passée.
    expect(composant.etape).toBe('termine');
  });

  // ── Messages d'échec ───────────────────────────────────────────────────────

  it('dit de se reconnecter plutôt que de réessayer quand la session a expiré', () => {
    deposer();
    composant.envoyer();
    http.expectOne((r) => r.url.includes('/apply/')).flush(
      { detail: 'Not authenticated' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(composant.erreur).toContain('Reconnectez-vous');
    expect(composant.etape).toBe('cv');
  });

  it('distingue un serveur injoignable d une erreur applicative', () => {
    deposer();
    composant.envoyer();
    http.expectOne((r) => r.url.includes('/apply/'))
        .error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });

    expect(composant.erreur).toContain('injoignable');
  });

  it('reprend le message du serveur quand il en donne un', () => {
    deposer();
    composant.envoyer();
    http.expectOne((r) => r.url.includes('/apply/')).flush(
      { detail: 'Vous avez déjà postulé à cette offre.' },
      { status: 400, statusText: 'Bad Request' },
    );

    expect(composant.erreur).toContain('déjà postulé');
  });
});
