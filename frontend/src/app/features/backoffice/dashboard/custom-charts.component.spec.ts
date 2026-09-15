import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import {
  ChartSeries, ChartSeriesService, DashboardConfig, SeriesDescriptor,
} from '../../../core/services/chart-series.service';
import { CustomChartsComponent } from './custom-charts.component';

/**
 * Le tableau de bord composable.
 *
 * Trois comportements qui se cassent silencieusement s'ils ne sont pas tenus :
 *
 * 1. **Un tableau vidé volontairement doit rester vide.** Sans la distinction
 *    « jamais personnalisé » / « vidé », retirer son dernier graphique ferait
 *    réapparaître la composition d'origine, et on ne pourrait jamais vider son
 *    tableau — un défaut qu'on met longtemps à comprendre.
 * 2. **Une source en panne ne doit pas emporter les autres.** Un tableau de
 *    bord qui disparaît en entier parce qu'une agrégation a un problème est
 *    pire qu'un trou.
 * 3. **Le sélecteur n'offre que ce que la donnée admet.** La règle vient du
 *    serveur ; le composant ne doit pas la redevenir.
 */
function descripteur(over: Partial<SeriesDescriptor> = {}): SeriesDescriptor {
  return {
    id: 'employees_by_gender',
    label: 'Effectif par genre',
    description: 'Répartition des employés actifs.',
    kind: 'CATEGORIELLE',
    allowed_types: ['bar', 'pie'],
    default_type: 'pie',
    category: 'Effectif',
    ...over,
  };
}

function serie(over: Partial<ChartSeries> = {}): ChartSeries {
  return {
    id: 'employees_by_gender',
    label: 'Effectif par genre',
    kind: 'CATEGORIELLE',
    points: [{ label: 'Femme', x: 'F', y: 7 }, { label: 'Homme', x: 'M', y: 9 }],
    unit: 'employés',
    allowed_types: ['bar', 'pie'],
    default_type: 'pie',
    ...over,
  };
}

describe('CustomChartsComponent', () => {
  let composant: CustomChartsComponent;
  let service: jasmine.SpyObj<ChartSeriesService>;

  beforeEach(() => {
    service = jasmine.createSpyObj('ChartSeriesService',
      ['catalog', 'series', 'config', 'saveConfig']);
    service.catalog.and.returnValue(of({ sources: [descripteur()] }));
    service.series.and.returnValue(of(serie()));
    service.saveConfig.and.returnValue(of({ charts: [], customized: true }));

    TestBed.configureTestingModule({
      imports: [CustomChartsComponent],
      providers: [{ provide: ChartSeriesService, useValue: service }],
    });
    composant = TestBed.createComponent(CustomChartsComponent).componentInstance;
  });

  function config(over: Partial<DashboardConfig> = {}): DashboardConfig {
    return { charts: [], customized: false, ...over };
  }

  // ── Composition ────────────────────────────────────────────────────────────

  it('propose une composition par défaut à qui n a jamais rien réglé', () => {
    service.config.and.returnValue(of(config({ customized: false })));
    composant.ngOnInit();
    expect(composant.cartes.length).toBeGreaterThan(0);
  });

  it('laisse vide un tableau vidé volontairement', () => {
    // Le cas qui se comprend mal quand il casse : `customized` à vrai avec zéro
    // graphique veut dire « j'ai tout retiré », pas « je n'ai rien réglé ».
    service.config.and.returnValue(of(config({ charts: [], customized: true })));
    composant.ngOnInit();
    expect(composant.cartes).toEqual([]);
  });

  it('restitue la composition enregistrée', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [{ id: 'c1', source_id: 'employees_by_gender',
                 chart_type: 'bar', title: 'Mon titre', span: 12 }],
    })));
    composant.ngOnInit();
    expect(composant.cartes.length).toBe(1);
    expect(composant.titre(composant.cartes[0])).toBe('Mon titre');
    expect(composant.cartes[0].config.span).toBe(12);
  });

  // ── Robustesse ─────────────────────────────────────────────────────────────

  it('une source en panne ne fait pas disparaître les autres', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [
        { id: 'c1', source_id: 'employees_by_gender', chart_type: 'pie', title: null, span: 6 },
        { id: 'c2', source_id: 'employees_by_gender', chart_type: 'bar', title: null, span: 6 },
      ],
    })));
    let appel = 0;
    service.series.and.callFake(() =>
      ++appel === 1 ? throwError(() => ({ status: 500 })) : of(serie()));

    composant.ngOnInit();

    expect(composant.cartes.length).toBe(2);
    expect(composant.cartes[0].erreur).toBeTruthy();
    expect(composant.cartes[1].serie).toBeTruthy();
  });

  it('retombe sur la composition par défaut si la configuration est illisible', () => {
    service.config.and.returnValue(throwError(() => ({ status: 500 })));
    composant.ngOnInit();
    expect(composant.cartes.length).toBeGreaterThan(0);
    expect(composant.chargement).toBeFalse();
  });

  // ── Types ──────────────────────────────────────────────────────────────────

  it('n offre que les types admis par la série', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [{ id: 'c1', source_id: 'employees_by_gender',
                 chart_type: 'pie', title: null, span: 6 }],
    })));
    composant.ngOnInit();
    expect(composant.typesPossibles(composant.cartes[0])).toEqual(['bar', 'pie']);
  });

  it('se rabat sur le catalogue quand la série n a pas encore répondu', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [{ id: 'c1', source_id: 'employees_by_gender',
                 chart_type: 'pie', title: null, span: 6 }],
    })));
    service.series.and.returnValue(throwError(() => ({ status: 500 })));
    composant.ngOnInit();
    // Le sélecteur reste utilisable même si la donnée manque.
    expect(composant.typesPossibles(composant.cartes[0])).toEqual(['bar', 'pie']);
  });

  it('changer de type enregistre la composition', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [{ id: 'c1', source_id: 'employees_by_gender',
                 chart_type: 'pie', title: null, span: 6 }],
    })));
    composant.ngOnInit();
    composant.changerType(composant.cartes[0], 'bar');

    expect(composant.cartes[0].config.chart_type).toBe('bar');
    const enregistre = service.saveConfig.calls.mostRecent().args[0];
    expect(enregistre.charts[0].chart_type).toBe('bar');
    expect(enregistre.customized).toBeTrue();
  });

  // ── Ajout ──────────────────────────────────────────────────────────────────

  it('choisir une source impose le type par défaut de CETTE source', () => {
    // Et non le dernier type choisi : une série temporelle et un camembert
    // n'ont pas les mêmes formes admissibles.
    service.config.and.returnValue(of(config()));
    composant.ngOnInit();
    composant.typeChoisi = 'bar';
    composant.surChoixSource('employees_by_gender');
    expect(composant.typeChoisi).toBe('pie');
  });

  it('ajouter place le graphique et enregistre', () => {
    service.config.and.returnValue(of(config({ charts: [], customized: true })));
    composant.ngOnInit();
    composant.surChoixSource('employees_by_gender');
    composant.titreChoisi = '  Ma répartition  ';
    composant.ajouter();

    expect(composant.cartes.length).toBe(1);
    expect(composant.cartes[0].config.title).toBe('Ma répartition');
    expect(service.saveConfig).toHaveBeenCalled();
  });

  it('n ajoute rien sans source choisie', () => {
    service.config.and.returnValue(of(config({ charts: [], customized: true })));
    composant.ngOnInit();
    composant.sourceChoisie = '';
    composant.ajouter();
    expect(composant.cartes).toEqual([]);
  });

  it('retirer enregistre le tableau vidé', () => {
    service.config.and.returnValue(of(config({
      customized: true,
      charts: [{ id: 'c1', source_id: 'employees_by_gender',
                 chart_type: 'pie', title: null, span: 6 }],
    })));
    composant.ngOnInit();
    composant.retirer(composant.cartes[0]);

    expect(composant.cartes).toEqual([]);
    const enregistre = service.saveConfig.calls.mostRecent().args[0];
    expect(enregistre.charts).toEqual([]);
    expect(enregistre.customized).toBeTrue();
  });
});
