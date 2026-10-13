import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CorrectionAdminComponent } from './correction-admin.component';

/**
 * Fenêtre des corrections d'administrateur (retrait de contrat, statut forcé) :
 * pas de confirmation sans motif écrit — il entre au journal d'audit.
 */
describe('CorrectionAdminComponent', () => {
  let fixture: ComponentFixture<CorrectionAdminComponent>;
  let composant: CorrectionAdminComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [CorrectionAdminComponent] });
    fixture = TestBed.createComponent(CorrectionAdminComponent);
    composant = fixture.componentInstance;
    composant.titre = 'Retirer le contrat';
    composant.choix = [{ value: 'ACCEPTED', label: 'Acceptée' }, { value: 'ON_HOLD', label: 'En réserve' }];
    composant.choixInitial = 'ON_HOLD';
    composant.ngOnChanges();
    fixture.detectChanges();
  });

  it('part du choix initial', () => {
    expect(composant.valeur).toBe('ON_HOLD');
  });

  it('refuse de confirmer sans motif suffisant', () => {
    const emis = spyOn(composant.confirmer, 'emit');
    composant.motif = '  ok ';
    composant.valider();
    expect(composant.valide).toBeFalse();
    expect(emis).not.toHaveBeenCalled();
  });

  it('émet le choix et le motif nettoyé', () => {
    const emis = spyOn(composant.confirmer, 'emit');
    composant.motif = '  Recrutement annulé  ';
    composant.valider();
    expect(emis).toHaveBeenCalledWith({ choix: 'ON_HOLD', motif: 'Recrutement annulé' });
  });

  it('ne se ferme pas pendant l application', () => {
    const ferme = spyOn(composant.annuler, 'emit');
    composant.enCours = true;
    composant.fermer();
    expect(ferme).not.toHaveBeenCalled();
  });
});
