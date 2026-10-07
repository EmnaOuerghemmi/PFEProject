import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';

import { BackofficeDashboardComponent } from './backoffice-dashboard.component';

describe('BackofficeDashboardComponent', () => {
  let component: BackofficeDashboardComponent;
  let fixture: ComponentFixture<BackofficeDashboardComponent>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [BackofficeDashboardComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(BackofficeDashboardComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ── Panneau « Créer un graphique » — reproduction du scénario signalé ──
  //
  // Le composant `app-select` isolé s'ouvrait sans problème (voir
  // select.component.spec.ts) : le blocage ne pouvait donc venir que de son
  // câblage DANS ce panneau précis, pas du composant lui-même.

  /** Composition commune, vue par l'administrateur (seul à pouvoir la modifier). */
  function repondreAuCatalogue(): void {
    // La composition d'abord : c'est elle qui déclenche le chargement du
    // catalogue, et seulement pour l'administrateur.
    http.match(r => r.url.endsWith('dashboard/config')).forEach(r => r.flush({
      charts: [], customized: false, builtin_visibility: {}, can_edit: true,
    }));
    http.match(r => r.url.endsWith('dashboard/series')).forEach(r => r.flush({
      sources: [
        { id: 'applications_by_status', label: 'Répartition des statuts',
          description: 'x', kind: 'CATEGORIELLE', allowed_types: ['bar', 'pie'],
          default_type: 'pie', category: 'Recrutement',
          y_label: 'Candidatures', x_label: 'Statut' },
      ],
    }));
  }

  // ── Visibilité par rôle ──

  it("verrouille « Créer un graphique » et l'œil pour un rôle qui ne peut pas modifier", () => {
    http.match(r => r.url.endsWith('dashboard/config')).forEach(r => r.flush({
      charts: [], customized: false, builtin_visibility: { status: 'ALL' }, can_edit: false,
    }));
    fixture.detectChanges();

    // Visibles, mais verrouillés : ni le bouton ni l'œil ne réagissent.
    const creer = fixture.debugElement.query(By.css('.card--add-row'));
    expect(creer).not.toBeNull();
    expect(creer.nativeElement.disabled).toBeTrue();
    expect(creer.nativeElement.classList).toContain('is-locked');
    const oeil = fixture.debugElement.query(By.css('app-visibility-menu .vis-btn'));
    expect(oeil.nativeElement.disabled).toBeTrue();
    component.ouvrirPanneau();
    expect(component.panneauOuvert).toBeFalse();
    // Le catalogue ne sert qu'à créer : il n'est même pas demandé.
    expect(http.match(r => r.url.endsWith('dashboard/series')).length).toBe(0);
  });

  it("n'affiche que les cartes partagées avec le rôle", () => {
    http.match(r => r.url.endsWith('dashboard/config')).forEach(r => r.flush({
      charts: [], customized: false, builtin_visibility: { status: 'RH' }, can_edit: false,
    }));
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.card--donut'))).not.toBeNull();
    expect(fixture.debugElement.query(By.css('.card--area'))).toBeNull();
    // L'évolution n'est pas partagée : sa série n'est pas demandée.
    expect(http.match(r => r.url.includes('dashboard/applications-timeline')).length).toBe(0);
  });

  it("montre l'œil sur chaque carte à l'administrateur", () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.css('app-visibility-menu')).length).toBe(6);
  });

  it("ouvre la liste de l'axe Y au clic, sans lever d'exception", () => {
    repondreAuCatalogue();
    fixture.detectChanges();

    const boutonCreer = fixture.debugElement.query(By.css('.card--add-row'));
    expect(boutonCreer).withContext('le catalogue doit être chargé pour voir le bouton').not.toBeNull();
    boutonCreer.nativeElement.click();
    fixture.detectChanges();

    expect(component.panneauOuvert).toBeTrue();

    const declencheurAxeY = fixture.debugElement.query(By.css('.dash-panel .sel-trigger'));
    expect(declencheurAxeY).withContext('le sélecteur Axe Y doit être rendu').not.toBeNull();

    expect(() => {
      declencheurAxeY.nativeElement.click();
      fixture.detectChanges();
    }).not.toThrow();

    const liste = fixture.debugElement.query(By.css('.dash-panel .sel-list'));
    expect(liste).withContext('la liste doit apparaître après le clic').not.toBeNull();
  });

  // Le clic sur le DÉCLENCHEUR passait déjà ; c'est le clic sur une OPTION qui
  // échouait à l'écran. Tant que les champs du panneau étaient des `<label>`,
  // ce clic remontait au label, qui le relayait au bouton du sélecteur et
  // rouvrait la liste — le choix ne prenait jamais.
  it("retient l'axe Y choisi dans la liste", () => {
    repondreAuCatalogue();
    fixture.detectChanges();

    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.dash-panel .sel-trigger')).nativeElement.click();
    fixture.detectChanges();

    const options = fixture.debugElement.queryAll(By.css('.dash-panel .sel-opt'));
    expect(options.length).withContext('le catalogue doit fournir au moins une mesure').toBeGreaterThan(0);
    options[0].nativeElement.click();
    fixture.detectChanges();

    expect(component.axeY).toBe('Candidatures');
    expect(fixture.debugElement.query(By.css('.dash-panel .sel-list')))
      .withContext('la liste doit se refermer sur le choix').toBeNull();
  });

  // ── L'invariant qui avait lâché ────────────────────────────────────────
  //
  // Mesuré dans un vrai navigateur : un `[options]` alimenté par un getter
  // était évalué 189 100 fois pour UN clic sur la liste de l'axe Y — le
  // différentiel d'itérables de `*ngFor` voyait des objets neufs à chaque
  // passe, la vue ne se stabilisait jamais, l'onglet se figeait. Le test
  // n'observe donc pas un rendu mais la STABILITÉ DES RÉFÉRENCES, qui est la
  // propriété réellement en cause.
  it('expose des listes de choix à référence stable', () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();

    for (const nom of ['axesYOptions', 'axesXOptions', 'typesDeLaSourceChoisieOptions'] as const) {
      const a = component[nom];
      fixture.detectChanges();
      expect(component[nom])
        .withContext(`${nom} doit rester la MÊME référence d'un cycle à l'autre ; `
          + 'un getter qui reconstruit son tableau empêche la vue de se stabiliser')
        .toBe(a);
    }

    // Même exigence pour les graphiques personnalisés, dont les formes
    // admissibles étaient calculées dans le gabarit.
    component.graphiquesPersonnalises.forEach(g => {
      const a = g.typeOptions;
      fixture.detectChanges();
      expect(g.typeOptions).toBe(a);
    });
  });

  it('met bien à jour les listes quand la donnée change', () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();

    expect(component.axesYOptions.map(o => o.value)).toEqual(['Candidatures']);
    component.surChoixAxeY('Candidatures');
    fixture.detectChanges();
    expect(component.axesXOptions.map(o => o.label)).toEqual(['Statut']);
  });

  // ── Le formulaire annonce d'emblée tout ce qu'il attend ────────────────
  // `ngModel` écrit la valeur initiale sur une micro-tâche : on attend la
  // stabilité avant de lire les libellés (« Tous » pour la visibilité).
  it("affiche les cinq champs dès l'ouverture, vides et sans en masquer aucun", async () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const intitules = fixture.debugElement
      .queryAll(By.css('.dash-panel .dash-field > span'))
      .map(e => (e.nativeElement as HTMLElement).textContent!.trim());

    expect(intitules).toEqual([
      'Axe Y — que voulez-vous compter ?',
      'Axe X — réparti selon quoi ?',
      'Type de graphique',
      'Qui peut voir ce graphique ?',
      'Titre (facultatif)',
    ]);

    // Aucun choix fait : les trois sélecteurs du graphique affichent « Choisir… » ;
    // la visibilité part de « Tous », le choix le plus courant.
    const libelles = fixture.debugElement
      .queryAll(By.css('.dash-panel .sel-trigger__label'))
      .map(e => (e.nativeElement as HTMLElement).textContent!.trim());
    expect(libelles).toEqual(['Choisir…', 'Choisir…', 'Choisir…', 'Tous']);
  });

  // `ngModel` applique `[disabled]` sur une micro-tâche (`NgModel._updateDisabled`),
  // d'où l'attente de stabilité avant de lire l'état de l'<input> du titre.
  it('active chaque champ seulement quand le choix précédent lui donne un sens', async () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();

    const boutons = () => fixture.debugElement
      .queryAll(By.css('.dash-panel .sel-trigger'))
      .map(e => (e.nativeElement as HTMLButtonElement).disabled);
    const titre = () => fixture.debugElement
      .query(By.css('.dash-panel input[name="titreChoisi"]')).nativeElement as HTMLInputElement;

    // À l'ouverture : seul l'axe Y est actionnable.
    await fixture.whenStable();
    fixture.detectChanges();
    expect(boutons()).toEqual([false, true, true, true]);
    expect(titre().disabled).toBeTrue();

    // L'axe Y choisi ouvre l'axe X. Le catalogue de test n'offrant qu'une
    // seule répartition, `surChoixAxeY` la retient d'office : tout s'active.
    component.surChoixAxeY('Candidatures');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(component.sourceChoisie).toBe('applications_by_status');
    expect(boutons()).toEqual([false, false, false, false]);
    expect(titre().disabled).toBeFalse();
  });

  it('refuse de dérouler un sélecteur inactif', () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();

    const axeX = fixture.debugElement.queryAll(By.css('.dash-panel .sel-trigger'))[1];
    axeX.nativeElement.click();
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.dash-panel .sel-list')))
      .withContext("aucune liste ne doit s'ouvrir tant que l'axe Y n'est pas choisi")
      .toBeNull();
  });

  it("n'enveloppe aucun app-select dans un <label>", () => {
    repondreAuCatalogue();
    fixture.detectChanges();
    fixture.debugElement.query(By.css('.card--add-row')).nativeElement.click();
    fixture.detectChanges();

    const sousLabel = (fixture.nativeElement as HTMLElement)
      .querySelectorAll('label app-select');
    expect(sousLabel.length)
      .withContext('un <label> relaie ses clics vers le <button> du sélecteur')
      .toBe(0);
  });
});
