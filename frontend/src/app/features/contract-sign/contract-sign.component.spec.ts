import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import { ContractSignComponent } from './contract-sign.component';

/**
 * Parcours critique n°5 — signature électronique du contrat.
 *
 * Dernière étape du recrutement, et la plus sensible juridiquement : la page
 * est publique (accès par jeton, sans compte). Les garde-fous testés ici
 * empêchent une signature sans consentement explicite, sans tracé, ou sur un
 * contrat qui n'est pas en attente de signature — trois cas qui rendraient
 * l'acte contestable.
 */
describe('ContractSignComponent — signature électronique', () => {
  let component: ContractSignComponent;
  let fixture: ComponentFixture<ContractSignComponent>;
  let http: HttpTestingController;

  const JETON = 'jeton-public-abc';

  function contrat(surcharges: Partial<any> = {}) {
    return {
      id: 'ct-1',
      candidate_name: 'Naima Elmi',
      job_title: 'Développeur Full Stack',
      status: 'SENT',
      contract_type: 'CDI',
      salary: 3000,
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
        {
          // Le composant lit le jeton dans l'URL : sans ce stub il
          // interrogerait le serveur avec une chaîne vide.
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => JETON } } },
        },
      ],
      imports: [ContractSignComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ContractSignComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  // ── Chargement ───────────────────────────────────────────────────────────

  it('should create', () => {
    fixture.detectChanges();
    http.expectOne(r => r.url.includes(JETON)).flush(contrat());
    expect(component).toBeTruthy();
  });

  it('charge le contrat correspondant au jeton de l URL', () => {
    fixture.detectChanges();

    const requete = http.expectOne(r => r.url.includes(JETON));
    requete.flush(contrat());

    expect(component.contract).toBeTruthy();
    expect(component.contract!.candidate_name).toBe('Naima Elmi');
    expect(component.loading).toBeFalse();
  });

  it('affiche un message clair sur un lien expire', () => {
    fixture.detectChanges();

    http.expectOne(r => r.url.includes(JETON)).flush(
      { detail: 'Contrat introuvable ou lien expiré.' },
      { status: 404, statusText: 'Not Found' },
    );

    expect(component.loading).toBeFalse();
    expect(component.error).toContain('expiré');
  });

  // ── Contrat signable ─────────────────────────────────────────────────────

  it('n autorise la signature que sur un contrat envoye', () => {
    fixture.detectChanges();
    http.expectOne(r => r.url.includes(JETON)).flush(contrat({ status: 'SENT' }));
    expect(component.isSignable).toBeTrue();

    // Un contrat déjà signé ou refusé ne doit plus pouvoir l'être.
    component.contract = contrat({ status: 'SIGNED' }) as any;
    expect(component.isSignable).toBeFalse();

    component.contract = contrat({ status: 'DECLINED' }) as any;
    expect(component.isSignable).toBeFalse();
  });

  // ── Garde-fous avant signature ───────────────────────────────────────────

  describe('conditions de soumission', () => {
    beforeEach(() => {
      fixture.detectChanges();
      http.expectOne(r => r.url.includes(JETON)).flush(contrat());
      // Situation nominale : tout est rempli.
      component.signerName = 'Naima Elmi';
      component.aLu = true;
      component.consent = true;
      component.hasDrawn = true;
    });

    it('accepte quand nom, consentement et trace sont fournis', () => {
      expect(component.canSubmit).toBeTrue();
    });

    it("refuse tant que le contrat complet n'est pas déclaré lu", () => {
      component.aLu = false;
      expect(component.canSubmit).toBeFalse();
      expect(component.manque.join(' ')).toContain('contrat');
    });

    it("l'ouverture du contrat complet est requise avant de pouvoir cocher « lu »", () => {
      expect(component.contratOuvert).toBeFalse();
      component.ouvrirLecture();
      http.expectOne(r => r.url.endsWith('/pdf')).flush(new Blob(['%PDF-'], { type: 'application/pdf' }));
      expect(component.contratOuvert).toBeTrue();
    });

    it('signale un échec de chargement du contrat sans bloquer la page', () => {
      component.ouvrirLecture();
      http.expectOne(r => r.url.endsWith('/pdf')).flush(new Blob([]), { status: 500, statusText: 'Server Error' });
      expect(component.contratOuvert).toBeFalse();
      expect(component.lectureErreur).toBeTruthy();
    });

    it('refuse sans consentement explicite', () => {
      component.consent = false;
      expect(component.canSubmit).toBeFalse();
    });

    it('refuse sans trace de signature', () => {
      component.hasDrawn = false;
      expect(component.canSubmit).toBeFalse();
    });

    it('refuse un nom trop court', () => {
      component.signerName = 'N';
      expect(component.canSubmit).toBeFalse();
    });

    it('refuse un nom compose uniquement d espaces', () => {
      component.signerName = '   ';
      expect(component.canSubmit).toBeFalse();
    });

    it('refuse un second envoi pendant la soumission', () => {
      // Évite la double signature par double clic.
      component.submitting = true;
      expect(component.canSubmit).toBeFalse();
    });

    it('n envoie rien au serveur si les conditions ne sont pas reunies', () => {
      component.consent = false;

      component.sign();

      http.expectNone(r => r.method === 'POST');
      expect(component.submitting).toBeFalse();
    });
  });

  // ── Refus du contrat ─────────────────────────────────────────────────────

  it('transmet le motif lors d un refus', () => {
    fixture.detectChanges();
    http.expectOne(r => r.url.includes(JETON)).flush(contrat());

    component.declineReason = 'Salaire insuffisant';
    component.confirmDecline();

    const requete = http.expectOne(
      r => r.url.includes('decline') || r.method === 'POST',
    );
    requete.flush(contrat({ status: 'DECLINED' }));

    expect(component.contract!.status).toBe('DECLINED');
    expect(component.submitting).toBeFalse();
    expect(component.showDecline).toBeFalse();
  });

  it('signale un echec de refus sans bloquer l interface', () => {
    fixture.detectChanges();
    http.expectOne(r => r.url.includes(JETON)).flush(contrat());

    component.declineReason = 'Motif';
    component.confirmDecline();
    http.expectOne(r => r.method === 'POST').flush(
      { detail: 'Action impossible.' },
      { status: 400, statusText: 'Bad Request' },
    );

    expect(component.submitting).toBeFalse();
    expect(component.error).toBeTruthy();
  });
});
