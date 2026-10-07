import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';

import { SelectComponent, SelectOption } from './select.component';

@Component({
  standalone: true,
  imports: [FormsModule, SelectComponent],
  template: `<app-select [(ngModel)]="valeur" [options]="options"></app-select>`,
})
class HoteTest {
  valeur = '';
  options: SelectOption[] = [
    { value: 'a', label: 'Candidatures' },
    { value: 'b', label: 'Candidats' },
  ];
}

@Component({
  standalone: true,
  imports: [FormsModule, SelectComponent],
  template: `<app-select [(ngModel)]="valeur" [options]="options" [recherche]="true"></app-select>`,
})
class HoteRecherche {
  valeur = '';
  options: SelectOption[] = [
    { value: 'e', label: 'Élodie Martin' },
    { value: 'a', label: 'Amine Ben Salah' },
    { value: 'm', label: 'Marie Dupont' },
  ];
}

describe('SelectComponent', () => {
  let fixture: ComponentFixture<HoteTest>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HoteTest] }).compileComponents();
    fixture = TestBed.createComponent(HoteTest);
    fixture.detectChanges();
  });

  function bouton() {
    return fixture.debugElement.query(By.css('.sel-trigger')).nativeElement as HTMLButtonElement;
  }

  it("ouvre la liste au clic sur le déclencheur, sans exception", () => {
    expect(fixture.debugElement.query(By.css('.sel-list'))).toBeNull();

    expect(() => {
      bouton().click();
      fixture.detectChanges();
    }).not.toThrow();

    const liste = fixture.debugElement.query(By.css('.sel-list'));
    expect(liste).not.toBeNull();
    expect(liste.queryAll(By.css('.sel-opt')).length).toBe(2);
  });

  it('ferme la liste au clic sur une option, et transmet la valeur', () => {
    bouton().click();
    fixture.detectChanges();

    const options = fixture.debugElement.queryAll(By.css('.sel-opt'));
    options[1].nativeElement.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.valeur).toBe('b');
    expect(fixture.debugElement.query(By.css('.sel-list'))).toBeNull();
  });

  it("ferme la liste au clic en dehors du composant", () => {
    bouton().click();
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('.sel-list'))).not.toBeNull();

    document.body.click();
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.sel-list'))).toBeNull();
  });

  it("n'ouvre rien de plus au second clic — le bouton referme", () => {
    bouton().click();
    fixture.detectChanges();
    bouton().click();
    fixture.detectChanges();
    expect(fixture.debugElement.query(By.css('.sel-list'))).toBeNull();
  });
});

/**
 * Recherche : le champ EST la barre de saisie. On y met le curseur, la liste
 * s'ouvre, et la frappe la filtre — sans clic de plus, sans seconde barre.
 * Le filtre ignore la casse et les accents.
 */
describe('SelectComponent — recherche', () => {
  let fixture: ComponentFixture<HoteRecherche>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HoteRecherche] }).compileComponents();
    fixture = TestBed.createComponent(HoteRecherche);
    fixture.detectChanges();
  });

  function champ(): HTMLInputElement {
    return fixture.debugElement.query(By.css('.sel-combo__input')).nativeElement as HTMLInputElement;
  }

  function saisir(texte: string): void {
    champ().value = texte;
    champ().dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  function touche(key: string): void {
    champ().dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }));
    fixture.detectChanges();
  }

  function libelles(): string[] {
    return fixture.debugElement.queryAll(By.css('.sel-opt')).map(o => o.nativeElement.textContent.trim());
  }

  function listeOuverte(): boolean {
    return !!fixture.debugElement.query(By.css('.sel-list'));
  }

  it('n\'est pas un bouton : le champ lui-même reçoit la saisie', () => {
    expect(champ().tagName).toBe('INPUT');
    expect(fixture.debugElement.query(By.css('button.sel-trigger'))).toBeNull();
  });

  it('ouvre la liste dès que le curseur arrive dans le champ', () => {
    expect(listeOuverte()).toBeFalse();

    champ().dispatchEvent(new Event('focus'));
    fixture.detectChanges();

    expect(listeOuverte()).toBeTrue();
    expect(libelles().length).toBe(3);
  });

  it('ouvre aussi la liste au clic sur le champ', () => {
    (fixture.debugElement.query(By.css('.sel-trigger')).nativeElement as HTMLElement).click();
    fixture.detectChanges();
    expect(listeOuverte()).toBeTrue();
  });

  it('filtre les options selon la saisie', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('mar');
    expect(libelles()).toEqual(['Élodie Martin', 'Marie Dupont']);
  });

  it('ignore la casse et les accents : « elodie » retrouve « Élodie »', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('ELODIE');
    expect(libelles()).toEqual(['Élodie Martin']);
  });

  it('rouvre la liste quand on tape alors qu\'elle était fermée', () => {
    saisir('amine');
    expect(listeOuverte()).toBeTrue();
    expect(libelles()).toEqual(['Amine Ben Salah']);
  });

  it('dit qu\'il n\'y a aucun résultat plutôt que d\'afficher une liste vide', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('zzz');
    expect(libelles()).toEqual([]);
    expect(fixture.debugElement.query(By.css('.sel-vide'))).not.toBeNull();
  });

  it('Entrée choisit l\'option visée — la première par défaut', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('amine');
    touche('Enter');

    expect(fixture.componentInstance.valeur).toBe('a');
    expect(listeOuverte()).toBeFalse();
  });

  it('les flèches déplacent la visée avant Entrée', () => {
    champ().dispatchEvent(new Event('focus'));
    fixture.detectChanges();
    touche('ArrowDown');
    touche('ArrowDown');
    touche('Enter');

    expect(fixture.componentInstance.valeur).toBe('m');   // troisième option
  });

  it('la visée ne sort pas de la liste', () => {
    champ().dispatchEvent(new Event('focus'));
    fixture.detectChanges();
    touche('ArrowUp');
    touche('Enter');
    expect(fixture.componentInstance.valeur).toBe('e');   // reste sur la première
  });

  it('une fois fermé, le champ affiche le libellé choisi', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('amine');
    touche('Enter');

    expect(champ().value).toBe('Amine Ben Salah');
  });

  it('Échap referme la liste sans rien choisir', () => {
    champ().dispatchEvent(new Event('focus'));
    fixture.detectChanges();
    touche('Escape');

    expect(fixture.componentInstance.valeur).toBe('');
    expect(listeOuverte()).toBeFalse();
  });

  it('une saisie qui s\'ajoute au libellé affiché le remplace au lieu de s\'y accoler', async () => {
    // Collage ou saisie assistée alors que le champ montre « Marie Dupont » :
    // aucune touche n'a vidé le champ, le texte s'est simplement ajouté.
    fixture.componentInstance.valeur = 'm';
    fixture.detectChanges();
    await fixture.whenStable();   // ngModel écrit sa valeur de façon asynchrone
    fixture.detectChanges();
    champ().value = 'Marie Dupontamine';
    champ().dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(libelles()).toEqual(['Amine Ben Salah']);
  });

  it('même liste ouverte, une saisie accolée au libellé ne garde que ce qui a été tapé', async () => {
    fixture.componentInstance.valeur = 'm';
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    // Le focus ouvre la liste, mais la saisie arrive avant que le champ ait été
    // vidé : le texte s'ajoute au libellé « Marie Dupont ».
    champ().dispatchEvent(new Event('focus'));
    champ().value = 'Marie Dupontamine';
    champ().dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(libelles()).toEqual(['Amine Ben Salah']);
  });

  it('repart d\'une saisie vide à chaque ouverture', () => {
    champ().dispatchEvent(new Event('focus'));
    saisir('mar');
    touche('Escape');

    champ().dispatchEvent(new Event('focus'));
    fixture.detectChanges();

    expect(libelles().length).toBe(3);
  });
});
