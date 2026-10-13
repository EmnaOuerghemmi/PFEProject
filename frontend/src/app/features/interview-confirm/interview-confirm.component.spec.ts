import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';

import { InterviewConfirmComponent } from './interview-confirm.component';
import { PublicInvitationView } from '../../core/services/recruitment.service';

/**
 * Heures de la page publique de confirmation d'entretien.
 *
 * Cas réel : un créneau stocké à 13h07 UTC s'affichait 15:07 sur un poste
 * réglé sur Paris, quand l'e-mail annonçait 14h07 (heure de Tunis). La page
 * affiche désormais le fuseau de la plateforme, quel que soit l'ordinateur.
 */
describe('InterviewConfirmComponent — heures dans le fuseau de la plateforme', () => {
  let composant: InterviewConfirmComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [InterviewConfirmComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => 'jeton' } } } },
      ],
    });
    composant = TestBed.createComponent(InterviewConfirmComponent).componentInstance;
    composant.invitation = { timezone: 'Africa/Tunis' } as PublicInvitationView;
  });

  it("affiche l'heure de Tunis, comme l'e-mail", () => {
    expect(composant.formatTime('2026-10-13T13:07:00Z')).toBe('14:07');
    expect(composant.libelleFuseau).toBe('heure de Tunis');
  });

  it('le jour suit le fuseau, pas celui du navigateur', () => {
    // 23h30 UTC le lundi = 0h30 le mardi à Tunis.
    expect(composant.formatDate('2026-10-12T23:30:00Z')).toBe('Mardi 13 octobre 2026');
  });

  it("garde Tunis si l'API ne précise pas le fuseau", () => {
    composant.invitation = {} as PublicInvitationView;
    expect(composant.formatTime('2026-10-13T13:07:00Z')).toBe('14:07');
  });
});
