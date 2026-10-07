import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { ApplicationsComponent } from './applications.component';
import { ConfirmService } from '../../../core/services/confirm.service';

/**
 * Parcours critique n°4 — changement de statut d'une candidature.
 *
 * Le statut déclenche des effets irréversibles côté serveur : passer en
 * ACCEPTED ouvre la génération de contrat, passer en REJECTED envoie un
 * e-mail de refus au candidat. Une erreur de câblage enverrait donc un
 * refus à la mauvaise personne.
 *
 * La suppression est couverte à part : elle est destructive et passe
 * désormais par une confirmation applicative. Un dialogue qui ne
 * s'afficherait pas supprimerait des dossiers sans validation.
 */
describe('ApplicationsComponent — statut et suppression', () => {
  let component: ApplicationsComponent;
  let fixture: ComponentFixture<ApplicationsComponent>;
  let http: HttpTestingController;
  let confirmService: ConfirmService;

  function candidature(surcharges: Partial<any> = {}) {
    return {
      id: 'app-1',
      candidate_id: 'c1',
      candidate_name: 'Naima Elmi',
      job_offer_id: 'j1',
      job_offer_title: 'Développeur Full Stack',
      cv_file_path: '/cv.pdf',
      status: 'PENDING',
      created_at: '2026-07-01T10:00:00Z',
      updated_at: '2026-07-01T10:00:00Z',
      ...surcharges,
    };
  }

  /** Répond au chargement initial déclenché par ngOnInit. */
  function chargementInitial(elements: any[] = [candidature()]) {
    http.expectOne(r => r.url.includes('/applications')).flush(elements);
  }


  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [ApplicationsComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplicationsComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    confirmService = TestBed.inject(ConfirmService);
    fixture.detectChanges();
  });

  it('should create', () => {
    chargementInitial();
    expect(component).toBeTruthy();
  });

  it('charge les candidatures au demarrage', () => {
    chargementInitial([candidature(), candidature({ id: 'app-2' })]);

    expect(component.applications.length).toBe(2);
    expect(component.applications[0].candidate_name).toBe('Naima Elmi');
  });

  // ── Changement de statut ─────────────────────────────────────────────────

  it('transmet le nouveau statut au serveur', () => {
    chargementInitial();

    component.updateStatus(component.applications[0], 'ACCEPTED');

    const requete = http.expectOne(
      r => r.url.includes('/applications/app-1') && r.method === 'PATCH',
    );
    expect(requete.request.body.status).toBe('ACCEPTED');
    requete.flush({});

    // La liste est rechargée pour refléter l'état réel du serveur plutôt
    // que de supposer que la mise à jour a abouti.
    http.expectOne(r => r.url.includes('/applications') && r.method === 'GET').flush([]);
  });

  it('recharge la liste apres un changement de statut', () => {
    chargementInitial();

    component.updateStatus(component.applications[0], 'REJECTED');
    http.expectOne(r => r.method === 'PATCH').flush({});

    http.expectOne(r => r.url.includes('/applications') && r.method === 'GET')
        .flush([candidature({ status: 'REJECTED' })]);

    expect(component.applications[0].status).toBe('REJECTED');
  });

  it('propose toujours le statut actuel, meme hors des quatre de base', () => {
    // Avant : un <select> à 4 options fixes s'affichait vide pour TEST_DONE,
    // INTERVIEW_SCHEDULED, NEGOTIATION, HIRED…
    for (const statut of ['TEST_DONE', 'INTERVIEW_SCHEDULED', 'NEGOTIATION', 'HIRED', 'WITHDRAWN']) {
      expect(component.statusOptions(statut)[0].value).toBe(statut);
    }
    // Les retours en arrière non admis ne sont pas proposés.
    expect(component.statusOptions('TEST_DONE').map(o => o.value)).not.toContain('PENDING');
    expect(component.statusOptions('NEGOTIATION').map(o => o.value)).toContain('INTERVIEW_SCHEDULED');
    chargementInitial();
  });

  // ── Suppression ──────────────────────────────────────────────────────────

  it('ne supprime rien si la confirmation est refusee', async () => {
    chargementInitial();
    spyOn(confirmService, 'askDelete').and.resolveTo(false);

    await component.deleteApp('app-1');

    http.expectNone(r => r.method === 'DELETE');
  });

  it('supprime apres confirmation explicite', async () => {
    chargementInitial();
    const demande = spyOn(confirmService, 'askDelete').and.resolveTo(true);

    await component.deleteApp('app-1');

    expect(demande).toHaveBeenCalled();
    http.expectOne(r => r.url.includes('/applications/app-1') && r.method === 'DELETE')
        .flush({});
    http.expectOne(r => r.method === 'GET').flush([]);
  });

  // ── Génération de contrat ────────────────────────────────────────────────

  it('n autorise la generation de contrat que sur un dossier accepte', () => {
    chargementInitial();

    expect(component.canGenerateContract(candidature({ status: 'ACCEPTED' }) as any)).toBeTrue();
    expect(component.canGenerateContract(candidature({ status: 'NEGOTIATION' }) as any)).toBeTrue();
    // Générer un contrat pour un dossier en attente ou rejeté n'a pas de sens.
    expect(component.canGenerateContract(candidature({ status: 'PENDING' }) as any)).toBeFalse();
    expect(component.canGenerateContract(candidature({ status: 'REJECTED' }) as any)).toBeFalse();
  });
});
