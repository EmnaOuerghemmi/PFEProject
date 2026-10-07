import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';

import { SelectComponent, SelectOption } from './select.component';

/**
 * Reproduit le balisage EXACT du panneau « Nouveau graphique » : le sélecteur
 * y est enveloppé dans un `<label>`, et ses options viennent d'un getter qui
 * reconstruit le tableau à chaque cycle de détection.
 *
 * Les deux détails sont absents de `select.component.spec.ts`, qui passe — et
 * c'est précisément pour ça qu'il passait sans rien prouver sur l'écran réel.
 */
@Component({
  standalone: true,
  imports: [FormsModule, SelectComponent],
  template: `
    <label class="dash-field">
      <span>Axe Y</span>
      <app-select [ngModel]="valeur" (ngModelChange)="valeur = $event"
                  name="axeY" [options]="optionsGetter"></app-select>
    </label>
  `,
})
class HoteAvecLabel {
  valeur = '';
  mesures = ['Candidatures', 'Candidats', 'Offres'];
  /** Comme `axesYOptions` : nouveau tableau, nouveaux objets, à chaque appel. */
  get optionsGetter(): SelectOption[] {
    return this.mesures.map(m => ({ value: m, label: m }));
  }
}

describe('SelectComponent enveloppé dans un <label> (panneau du dashboard)', () => {
  let fixture: ComponentFixture<HoteAvecLabel>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HoteAvecLabel] }).compileComponents();
    fixture = TestBed.createComponent(HoteAvecLabel);
    fixture.detectChanges();
  });

  function declencheur(): HTMLButtonElement {
    return fixture.debugElement.query(By.css('.sel-trigger')).nativeElement;
  }
  function liste() {
    return fixture.debugElement.query(By.css('.sel-list'));
  }

  it("s'ouvre au clic sur le déclencheur", () => {
    declencheur().click();
    fixture.detectChanges();
    expect(liste()).withContext('la liste doit être ouverte').not.toBeNull();
  });

  it('choisit une option et se referme — le <label> ne doit pas rouvrir la liste', () => {
    declencheur().click();
    fixture.detectChanges();

    const options = fixture.debugElement.queryAll(By.css('.sel-opt'));
    expect(options.length).toBe(3);
    options[1].nativeElement.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.valeur).toBe('Candidats');
    expect(liste()).withContext('la liste doit être refermée après le choix').toBeNull();
  });

  it("le clic sur le <span> du label ne doit pas laisser la liste dans un état incohérent", () => {
    const texte = fixture.debugElement.query(By.css('.dash-field span')).nativeElement as HTMLElement;
    texte.click();
    fixture.detectChanges();

    // Le navigateur relaie ce clic vers le bouton (premier descendant labelable).
    // Le résultat doit rester cohérent avec l'état interne du composant.
    const composant = fixture.debugElement.query(By.directive(SelectComponent))
      .componentInstance as SelectComponent;
    expect(!!liste()).withContext("DOM et état interne doivent concorder").toBe(composant.ouvert);
  });
});
