import {
  Component, ElementRef, HostBinding, HostListener, Input, OnDestroy, ViewChild, forwardRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

export interface SelectOption {
  value: string;
  label: string;
}

/** Minuscules, sans accents : la forme sur laquelle le filtre compare. */
function normaliser(texte: string): string {
  return texte.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
}

/**
 * Remplace le `<select>` natif là où sa liste déroulante OUVERTE doit
 * ressembler au reste de l'application.
 *
 * Le `<select>` lui-même se stylise très bien — bordure, fond, flèche. Sa
 * POPUP ouverte, elle, est dessinée par le navigateur en dehors du DOM
 * stylable : Chromium lui impose sa propre surbrillance (le bleu système) et
 * ses coins carrés, sans qu'aucune règle CSS — même sur les `<option>` — ne
 * puisse les changer. C'est une limite de la plateforme web, pas un oubli de
 * style : la seule sortie est de ne plus utiliser l'élément natif pour ce
 * besoin précis.
 *
 * `ControlValueAccessor` pour que `[(ngModel)]` fonctionne exactement comme
 * sur un `<select>` — aucun appelant n'a besoin de changer sa logique.
 */
@Component({
  selector: 'app-select',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="sel">
      <button *ngIf="!recherche; else champRecherche" type="button" class="sel-trigger"
              (click)="basculer($event)"
              [class.sel-trigger--nu]="apparence === 'nu'"
              [class.sel-trigger--pilule]="apparence === 'pilule'"
              [class.sel-trigger--champ]="apparence === 'champ'"
              [class.sel-trigger--vide]="!valeur"
              [disabled]="desactive"
              [attr.aria-expanded]="ouvert" [attr.aria-label]="ariaLabel || null">
        <span class="sel-trigger__label">{{ labelCourant }}</span>
        <svg class="sel-chevron" [class.sel-chevron--on]="ouvert"
             width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>

      <!-- Avec « recherche », le champ EST la barre de recherche : on y met le
           curseur, la liste s'ouvre, et la frappe la filtre. Pas de seconde
           barre dans la liste. Une <div> et non un <button> : un bouton ne
           peut pas contenir de champ de saisie. -->
      <ng-template #champRecherche>
        <div class="sel-trigger sel-combo"
             [class.sel-trigger--nu]="apparence === 'nu'"
             [class.sel-trigger--pilule]="apparence === 'pilule'"
             [class.sel-trigger--champ]="apparence === 'champ'"
             [class.sel-trigger--vide]="!valeur"
             [class.sel-trigger--desactive]="desactive"
             (click)="surClicChamp($event)">
          <input type="text" class="sel-combo__input" role="combobox" autocomplete="off" spellcheck="false"
                 aria-autocomplete="list" [attr.aria-expanded]="ouvert"
                 [attr.aria-label]="ariaLabel || null" [disabled]="desactive"
                 [value]="ouvert ? requete : labelValeur"
                 [placeholder]="ouvert && valeur ? labelValeur : placeholder"
                 (focus)="surFocus()" (input)="filtrer($any($event.target).value)"
                 (keydown)="surToucheChamp($event)">
          <svg class="sel-chevron" [class.sel-chevron--on]="ouvert" (click)="basculer($event)"
               width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
      </ng-template>

      <!-- Le mousedown annulé en mode recherche : sans ça, appuyer sur une option
           retire le focus du champ, qui ferme la liste AVANT que le clic ne
           soit pris en compte. -->
      <ul #liste class="sel-list" *ngIf="ouvert" role="listbox" (click)="$event.stopPropagation()"
          (mousedown)="recherche && $event.preventDefault()"
          [class.sel-list--flottante]="flottante" [ngStyle]="flottante ? positionFlottante : null">
        <li *ngFor="let o of optionsAffichees; let i = index; trackBy: parValeur" role="option"
            [attr.aria-selected]="o.value === valeur"
            class="sel-opt" [class.sel-opt--on]="o.value === valeur"
            [class.sel-opt--actif]="recherche && i === indexActif"
            (click)="choisir(o.value, $event)">{{ o.label }}</li>
        <li class="sel-vide" *ngIf="recherche && !optionsAffichees.length" role="presentation">Aucun résultat</li>
      </ul>
    </div>
  `,
  styles: [`
    /* Élément personnalisé : sans ce reset, l'hôte reste \`inline\` par défaut
       et ignore largeur/min-width posées depuis l'extérieur (même piège que
       rencontré sur \`app-chart\`). Les flex-items sont « blockifiés »
       automatiquement par la spec, donc ça passait inaperçu ici — mais un
       futur usage hors d'un conteneur flex y serait exposé sans ce reset. */
    :host { display: inline-block; }
    :host(.sel-host--champ) { display: block; width: 100%; }
    .sel { position: relative; }

    .sel-trigger {
      display: flex; align-items: center; justify-content: space-between;
      gap: .4rem; width: 100%;
      color: var(--c-ink, #1B2B2B);
      padding: .32rem 1.6rem .32rem .6rem;
      border: 1px solid var(--c-line-strong, #DACFB8);
      border-radius: var(--r-sm, 10px);
      background: var(--c-surface, #FFFFFF);
      font: inherit; font-size: var(--fs-2xs, .7rem); font-weight: 700;
      cursor: pointer;
      transition: border-color .14s;
    }
    .sel-trigger:hover:not(:disabled) { border-color: var(--c-gold, #10B981); }
    /* Un champ pas encore utilisable doit se lire comme tel — sans disparaître,
       pour que la forme du formulaire reste stable d'un bout à l'autre. */
    .sel-trigger:disabled {
      cursor: not-allowed;
      background: var(--c-surface-2, #FBF8F1);
      border-color: var(--c-line, #ECE3CF);
      color: var(--c-muted, #788888);
    }
    .sel-trigger:disabled .sel-chevron { opacity: .5; }

    .sel-trigger--nu {
      padding: 0;
      border: none;
      background: transparent;
      font-size: inherit; font-weight: inherit; color: inherit;
    }
    .sel-trigger--nu:hover:not(:disabled) { border-color: transparent; }
    .sel-trigger--nu:focus-visible { outline-offset: 2px; }
    .sel-trigger:focus-visible { outline: 2px solid var(--c-gold, #10B981); outline-offset: 1px; }
    /* Pastille de tableau (statut d'une candidature) : forme pilule, fond crème. */
    .sel-trigger--pilule {
      min-width: 150px;
      padding: 6px 28px 6px 12px;
      border-color: var(--c-line, #ECE3CF);
      border-radius: var(--r-pill, 999px);
      background: var(--c-canvas-soft, #FAF6EC);
      font-size: var(--fs-xs, .75rem); font-weight: 600;
      position: relative;
    }
    .sel-trigger--pilule .sel-chevron { position: absolute; right: 10px; }
    .sel-trigger--pilule:disabled { background: var(--c-line-cool, #E8E1D2); }
    /* Champ de formulaire : même gabarit que \`.input\` (42px, rayon xs). */
    .sel-trigger--champ {
      height: var(--sel-champ-hauteur, 42px);
      padding: 0 14px;
      background: var(--c-surface-2, #FBF8F1);
      border-color: var(--sel-champ-bord, var(--c-line-strong, #DACFB8));
      border-radius: var(--sel-champ-rayon, var(--r-xs, 8px));
      font: 500 var(--fs-sm, .8125rem)/1.4 var(--font-sans, inherit);
      transition: border-color .14s, box-shadow .14s, background .14s;
    }
    .sel-trigger--champ:hover:not(:disabled) { border-color: var(--c-muted-2, #A4B0B0); }
    .sel-trigger--champ[aria-expanded="true"],
    .sel-trigger--champ:focus-visible {
      outline: none;
      background: var(--c-surface, #FFFFFF);
      border-color: var(--c-gold, #10B981);
      box-shadow: 0 0 0 3px rgba(16, 185, 129, .16);
    }
    .sel-trigger--champ .sel-chevron { width: 16px; height: 16px; color: var(--c-ink-soft, #3D4F4F); }
    .sel-trigger--champ[aria-expanded="true"] .sel-chevron { color: var(--c-gold, #10B981); }
    /* Option vide choisie (« -- Sélectionner -- ») : se lit comme un placeholder. */
    .sel-trigger--champ.sel-trigger--vide { color: var(--c-muted-2, #A4B0B0); }
    .sel-trigger__label {
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .sel-chevron { flex-shrink: 0; color: var(--c-muted, #788888); transition: transform .16s; }
    .sel-chevron--on { transform: rotate(180deg); }

    .sel-list {
      position: absolute; z-index: 30;
      top: calc(100% + 4px); left: 0;
      min-width: 100%; max-height: 240px; overflow-y: auto;
      margin: 0; padding: 4px;
      list-style: none;
      border: 1px solid var(--c-line-strong, #DACFB8);
      border-radius: var(--r-sm, 10px);
      background: var(--c-surface, #FFFFFF);
      box-shadow: var(--sh-md, 0 8px 20px rgba(27,43,43,.12));
    }
    /* Liste hors du flux : échappe aux conteneurs en overflow (tableaux). */
    /* Rattachée au body (voir listeRef) : elle doit passer au-dessus des
       tiroirs et modales de l'appli, qui montent jusqu'à z-index 30000. */
    .sel-list--flottante { position: fixed; z-index: 2147483000; top: auto; left: auto; border-radius: 14px; padding: 6px; }
    /* Largeur bornée à l'écran : un libellé trop long passe à la ligne au lieu de déborder. */
    .sel-list--flottante .sel-opt { white-space: normal; overflow-wrap: anywhere; }
    .sel-opt {
      padding: .45rem .6rem;
      border-radius: var(--r-xs, 8px);
      color: var(--c-ink, #1B2B2B);
      font-size: var(--fs-sm, .8125rem);
      white-space: nowrap;
      cursor: pointer;
    }
    .sel-opt:hover { background: var(--c-surface-2, #FBF8F1); }
    /* Option visée au clavier (flèches) : même teinte que le survol. */
    .sel-opt--actif { background: var(--c-surface-2, #FBF8F1); }

    /* Mode recherche : le champ reçoit la saisie. Il garde la boîte du
       déclencheur (\`.sel-trigger\`), seul son contenu change. */
    .sel-combo { cursor: text; }
    .sel-combo__input {
      flex: 1; min-width: 0;
      padding: 0; border: 0; outline: 0;
      background: transparent;
      /* Pas \`inherit\` : l'état « vide » grise le texte du bouton, et la frappe
         ne doit pas s'afficher en gris. */
      color: var(--c-ink, #1B2B2B);
      font: inherit; text-overflow: ellipsis;
    }
    .sel-combo__input::placeholder { color: var(--c-muted-2, #A4B0B0); opacity: 1; }
    .sel-combo .sel-chevron { cursor: pointer; }
    .sel-trigger--champ:focus-within {
      outline: none;
      background: var(--c-surface, #FFFFFF);
      border-color: var(--c-gold, #10B981);
      box-shadow: 0 0 0 3px rgba(16, 185, 129, .16);
    }
    /* Champ pas encore utilisable : même apparence que le bouton désactivé. */
    .sel-trigger.sel-trigger--desactive {
      pointer-events: none;
      background: var(--c-surface-2, #FBF8F1);
      border-color: var(--c-line, #ECE3CF);
    }
    .sel-trigger--desactive .sel-combo__input { color: var(--c-muted, #788888); }
    .sel-trigger--desactive .sel-chevron { opacity: .5; }
    .sel-vide {
      padding: .6rem; text-align: center;
      color: var(--c-muted, #788888); font-size: var(--fs-sm, .8125rem);
    }
    .sel-opt--on { background: var(--c-gold-soft, #D1FAE5); color: var(--c-gold-ink, #064E3B); font-weight: 700; }

    @media (prefers-reduced-motion: reduce) {
      .sel-trigger, .sel-chevron { transition: none; }
    }
  `],
  providers: [{
    provide: NG_VALUE_ACCESSOR,
    useExisting: forwardRef(() => SelectComponent),
    multi: true,
  }],
})
export class SelectComponent implements ControlValueAccessor, OnDestroy {
  @Input() options: SelectOption[] = [];
  @Input() ariaLabel = '';
  @Input() placeholder = 'Choisir…';
  /**
   * Un champ inactif reste AFFICHÉ. C'est voulu : dans un formulaire en
   * cascade, faire apparaître les champs au fur et à mesure fait bouger la
   * mise en page sous le curseur et cache la suite du parcours. Montrer les
   * champs grisés dit à la fois « voici tout ce qu'il y a à remplir » et
   * « pas encore celui-ci ».
   */
  @Input() desactive = false;
  /**
   * `nu` retire la boîte du déclencheur — bordure, fond, rembourrage — pour
   * les cas où le conteneur appelant EST déjà la boîte (une pastille de barre
   * de filtres, par exemple). Sans ça, on empile deux bordures concentriques.
   * Le composant garde la main sur son propre style plutôt que d'obliger
   * l'appelant à percer l'encapsulation avec `::ng-deep`.
   */
  @Input() apparence: 'boite' | 'nu' | 'pilule' | 'champ' = 'boite';
  /** Un champ de formulaire occupe toute la largeur de sa colonne, comme `.input`. */
  @HostBinding('class.sel-host--champ') get estChamp(): boolean { return this.apparence === 'champ'; }
  /**
   * Liste en `position: fixed`, calée sous le déclencheur (ou au-dessus s'il
   * manque de place). À utiliser dans un conteneur en `overflow` — un tableau
   * défilant — qui couperait sinon la liste ancrée des dernières lignes.
   */
  @Input() flottante = false;
  /**
   * Le champ devient sa propre barre de recherche : on y met le curseur, la
   * liste s'ouvre, et ce qu'on tape la filtre. Utile dès qu'une liste dépasse
   * une dizaine d'entrées — offres, candidats — où défiler pour retrouver un nom
   * est plus long que de le taper. Le filtre ignore la casse et les accents :
   * « elodie » retrouve « Élodie ». Flèches et Entrée choisissent au clavier.
   */
  @Input() recherche = false;
  positionFlottante: Record<string, string> = {};

  requete = '';
  /** Option visée au clavier dans la liste filtrée. */
  indexActif = 0;
  // Vrai le temps de rendre le focus au champ par code : le gestionnaire de
  // focus rouvrirait sinon la liste que l'on vient de fermer en choisissant.
  private ignorerFocus = false;
  /** Instant d'ouverture de la liste, pour distinguer un vrai défilement de celui que le navigateur fait en amenant le champ à l'écran. */
  private ouvertA = 0;
  // Résultat du filtre mémorisé : le gabarit lit `optionsAffichees` plusieurs
  // fois par cycle, et un tableau neuf à chaque lecture ferait échouer la
  // vérification de changement (NG0100) en développement.
  private filtreOptions: SelectOption[] | null = null;
  private filtreRequete = '';
  private filtreResultat: SelectOption[] = [];

  get optionsAffichees(): SelectOption[] {
    if (!this.recherche || !this.requete.trim()) return this.options;
    if (this.filtreOptions !== this.options || this.filtreRequete !== this.requete) {
      const q = normaliser(this.requete);
      this.filtreResultat = this.options.filter(o => normaliser(o.label).includes(q));
      this.filtreOptions = this.options;
      this.filtreRequete = this.requete;
    }
    return this.filtreResultat;
  }

  /**
   * Liste flottante déplacée dans `document.body` dès qu'elle apparaît.
   *
   * `position: fixed` ne suffit pas : un ancêtre porteur d'un `transform`
   * (le tiroir du formulaire d'offre, une modale centrée en translate) devient
   * son repère, et la liste s'ouvrait alors décalée, hors de la zone visible —
   * « elle ne s'ouvre plus ». Rattachée au body, elle échappe à tout transform
   * et à tout overflow. Les styles encapsulés suivent (ils ciblent des
   * attributs, pas une position dans l'arbre) et Angular la retire où qu'elle
   * soit (`Renderer2.removeChild` appelle `node.remove()`).
   */
  private listeEl: HTMLElement | null = null;
  @ViewChild('liste') set listeRef(ref: ElementRef<HTMLElement> | undefined) {
    this.listeEl = ref?.nativeElement ?? null;
    if (this.listeEl && this.flottante) document.body.appendChild(this.listeEl);
  }

  valeur: string | null = null;
  ouvert = false;

  private onChange: (v: string) => void = () => {};
  private onTouched: () => void = () => {};

  constructor(private hote: ElementRef<HTMLElement>) {}

  writeValue(v: string): void { this.valeur = v ?? null; }
  registerOnChange(fn: (v: string) => void): void { this.onChange = fn; }
  registerOnTouched(fn: () => void): void { this.onTouched = fn; }

  // Pas de `setDisabledState` ici — volontairement.
  //
  // `setUpControl` l'appelle à l'initialisation avec l'état du contrôle, donc
  // `false` pour un `ngModel` ordinaire. Il écrasait alors l'entrée
  // `[desactive]` que l'appelant venait de poser, et tous les champs
  // repartaient actifs (constaté en test : les sélecteurs censés être grisés
  // se déroulaient quand même). `desactive` reste donc l'unique source de
  // vérité, et l'état s'applique de façon synchrone. Si un jour un
  // `FormControl.disable()` doit piloter ce composant, il faudra combiner les
  // deux sources, pas remplacer l'une par l'autre.

  /**
   * Sans `trackBy`, le différentiel d'itérables compare les options par
   * IDENTITÉ d'objet. Un appelant qui construit `[options]` dans un getter
   * livre des objets neufs à chaque cycle de détection : la liste est alors
   * reconstruite en boucle et la vue ne se stabilise jamais — fil principal
   * bloqué, onglet figé (constaté ici même). La bonne correction est côté
   * appelant (un champ, pas un getter), mais un composant partagé doit rester
   * sûr quoi qu'on lui passe : on compare donc les options par leur valeur.
   */
  parValeur(_: number, o: SelectOption): string { return o.value; }

  get labelCourant(): string {
    return this.options.find(o => o.value === this.valeur)?.label ?? this.placeholder;
  }

  /** Libellé de la valeur choisie, vide s'il n'y en a pas (le champ montre alors le placeholder). */
  get labelValeur(): string {
    return this.options.find(o => o.value === this.valeur)?.label ?? '';
  }

  private declencheurEl(): HTMLElement {
    return this.hote.nativeElement.querySelector('.sel-trigger') as HTMLElement;
  }

  /**
   * Le curseur arrive dans le champ : on ouvre la liste, et on sélectionne le
   * libellé affiché pour que la frappe le REMPLACE. Si la liste ne s'ouvre pas
   * (elle vient d'être fermée), c'est cette sélection qui évite que la frappe
   * s'ajoute au libellé.
   */
  surFocus(): void {
    this.ouvrirListe();
    this.selectionnerTexte();
  }

  /** Ouvre la liste. Sans effet si elle l'est déjà : le focus ET le clic y mènent. */
  ouvrirListe(): void {
    if (this.ouvert || this.desactive || this.ignorerFocus) return;
    this.ouvert = true;
    this.ouvertA = Date.now();
    this.requete = '';
    this.indexActif = 0;
    this.onTouched();
    if (this.flottante) {
      this.placerListe(this.declencheurEl());
      window.addEventListener('scroll', this.fermerSurDefilement, true);
    }
  }

  private champSaisie(): HTMLInputElement | null {
    return this.hote.nativeElement.querySelector<HTMLInputElement>('.sel-combo__input');
  }

  private rendreFocus(): void {
    const champ = this.champSaisie();
    if (!champ) return;
    this.ignorerFocus = true;
    champ.focus();
    this.ignorerFocus = false;
    this.selectionnerTexte();
  }

  /**
   * Sélectionne le libellé affiché, pour que la frappe suivante le REMPLACE au
   * lieu de s'y ajouter. Différé : le libellé n'est écrit dans le champ qu'au
   * prochain cycle de détection, et le sélectionner avant ne servirait à rien.
   */
  private selectionnerTexte(): void {
    setTimeout(() => this.champSaisie()?.select());
  }

  /**
   * `stopPropagation` : sans elle, ce même clic continue de remonter jusqu'à
   * `document`, où `surClicDocument` ci-dessous pourrait le lire comme un
   * « clic en dehors » — l'ordre bubble place normalement ce gestionnaire
   * AVANT celui du document, mais rien ne garantit qu'un navigateur ou une
   * version future s'y tienne. Autant fermer ce chemin plutôt que de
   * dépendre d'un ordre d'exécution implicite.
   */
  basculer(evt: MouseEvent): void {
    evt.stopPropagation();
    if (this.desactive) return;
    if (this.ouvert) {
      this.fermer();
    } else {
      this.ouvrirListe();
      if (this.recherche) this.rendreFocus();
    }
  }

  /** Clic sur le champ de recherche : ouvre la liste, sans jamais la refermer
   *  (on y place le curseur) — la flèche, elle, bascule. */
  surClicChamp(evt: MouseEvent): void {
    evt.stopPropagation();
    if (this.desactive || this.ouvert) return;
    this.ouvrirListe();
    this.rendreFocus();
  }

  /**
   * `preventDefault` n'est pas une précaution de style : c'est ce qui rend ce
   * composant utilisable sous un `<label>`.
   *
   * Un `<label>` relaie tout clic qu'il reçoit vers son premier descendant
   * « labelable » — et le déclencheur ci-dessus est un `<button>`, qui en est
   * un. Sans cette ligne, choisir une option envoyait le clic remonter jusqu'au
   * label, qui le renvoyait aussitôt au bouton : `basculer()` repassait derrière
   * `choisir()` et rouvrait la liste. Vu de l'écran, la liste refusait tout
   * choix. Ce relais EST l'action par défaut du clic sur le label : l'annuler
   * suffit à le couper.
   *
   * Le balisage appelant a été corrigé en parallèle (plus de `<label>` autour
   * d'un `app-select`), mais un composant partagé ne peut pas dépendre de la
   * discipline de ses appelants pour rester fonctionnel.
   */
  choisir(v: string, evt?: MouseEvent): void {
    evt?.preventDefault();
    evt?.stopPropagation();
    this.valeur = v;
    this.onChange(v);
    this.fermer();
  }

  /** Saisie dans le champ : filtre la liste, et la rouvre si elle était fermée. */
  filtrer(texte: string): void {
    // Première saisie d'une recherche alors que le champ affichait encore le
    // libellé choisi (collage, saisie assistée : rien n'a pu le vider avant) :
    // le texte s'y est ajouté, on retire le libellé pour ne garder que ce qui
    // a été tapé. `requete` vide = aucune frappe n'a encore eu lieu, donc ce
    // préfixe n'est pas de la saisie.
    const libelle = this.labelValeur;
    if (!this.requete && libelle && texte.startsWith(libelle)) texte = texte.slice(libelle.length);
    if (!this.ouvert) this.ouvrirListe();
    this.requete = texte;
    this.indexActif = 0;
  }

  private deplacerActif(pas: number): void {
    const n = this.optionsAffichees.length;
    if (!n) return;
    this.indexActif = Math.min(n - 1, Math.max(0, this.indexActif + pas));
    setTimeout(() => this.listeEl?.querySelectorAll('.sel-opt')[this.indexActif]
      ?.scrollIntoView({ block: 'nearest' }));
  }

  /**
   * Clavier du champ de recherche : flèches pour viser, Entrée pour choisir,
   * Échap pour refermer, Tab pour passer au champ suivant.
   *
   * Géré ICI et non par le `keydown.escape` de l'hôte : la liste flottante est
   * rattachée au `body`, hors de l'hôte, mais le champ, lui, est bien dedans.
   */
  surToucheChamp(evt: KeyboardEvent): void {
    switch (evt.key) {
      case 'ArrowDown':
        evt.preventDefault();
        if (this.ouvert) this.deplacerActif(1); else this.ouvrirListe();
        break;
      case 'ArrowUp':
        evt.preventDefault();
        if (this.ouvert) this.deplacerActif(-1);
        break;
      case 'Enter': {
        evt.preventDefault();
        if (!this.ouvert) { this.ouvrirListe(); break; }
        const visee = this.optionsAffichees[this.indexActif];
        if (visee) {
          this.choisir(visee.value);
          this.rendreFocus();
        }
        break;
      }
      case 'Escape':
        if (this.ouvert) {
          evt.preventDefault();
          this.fermer();
          this.selectionnerTexte();
        }
        break;
      case 'Tab':
        this.fermer();
        break;
      default:
        // Frappe alors que le champ est fermé mais garde le focus (après Échap
        // ou un choix) : il affiche le libellé choisi, que la frappe viendrait
        // compléter au lieu de le remplacer. On le vide avant que le caractère
        // n'y entre.
        if (!this.ouvert && evt.key.length === 1 && !evt.ctrlKey && !evt.metaKey && !evt.altKey) {
          this.ouvrirListe();
          (evt.target as HTMLInputElement).value = '';
        }
    }
  }

  /** Ferme au clic ailleurs — le comportement attendu d'une liste déroulante. */
  @HostListener('document:click', ['$event'])
  surClicDocument(evt: MouseEvent): void {
    if (this.ouvert && !this.hote.nativeElement.contains(evt.target as Node)) {
      this.ouvert = false;
    }
  }

  @HostListener('keydown.escape')
  surEchap(): void { this.fermer(); }

  /**
   * Une liste fixe ne suit pas le défilement : on la referme plutôt que de la
   * laisser flotter. Écoute en CAPTURE, car les tableaux défilent souvent dans
   * un conteneur interne dont le `scroll` ne remonte pas jusqu'à `window`.
   */
  private readonly fermerSurDefilement = (evt: Event) => {
    const cible = evt.target as Node;
    // La liste elle-même peut défiler (beaucoup d'options) : ce n'est pas une raison de fermer.
    if (this.listeEl?.contains(cible) || this.hote.nativeElement.contains(cible)) return;
    // Juste après l'ouverture, le défilement vient du navigateur qui amène le
    // champ à l'écran (focus au clavier, champ en bas de modale) : fermer la
    // liste ici la ferait disparaître à peine ouverte. On la recale plutôt.
    if (Date.now() - this.ouvertA < 400) {
      this.placerListe(this.declencheurEl());
      return;
    }
    this.fermer();
  };

  @HostListener('window:resize')
  surRedimension(): void { if (this.flottante) this.fermer(); }

  ngOnDestroy(): void {
    this.listeEl?.remove();
    window.removeEventListener('scroll', this.fermerSurDefilement, true);
  }

  private fermer(): void {
    this.ouvert = false;
    this.requete = '';
    window.removeEventListener('scroll', this.fermerSurDefilement, true);
  }

  private placerListe(declencheur: HTMLElement): void {
    const r = declencheur.getBoundingClientRect();
    const hauteurMax = 240;
    const enHaut = window.innerHeight - r.bottom < hauteurMax + 12 && r.top > window.innerHeight - r.bottom;
    // Horizontalement : on s'ancre du côté qui a le plus de place, et la
    // largeur est bornée à la fenêtre — sinon une option longue pousse la
    // liste hors de l'écran (champ proche du bord droit).
    const marge = 12;
    const ancreDroite = r.left > window.innerWidth - r.right;
    const place = ancreDroite ? r.right - marge : window.innerWidth - r.left - marge;
    this.positionFlottante = {
      ...(ancreDroite
        ? { right: `${window.innerWidth - r.right}px` }
        : { left: `${r.left}px` }),
      minWidth: `${Math.min(r.width, place)}px`,
      maxWidth: `${Math.max(place, r.width)}px`,
      ...(enHaut
        ? { bottom: `${window.innerHeight - r.top + 6}px` }
        : { top: `${r.bottom + 6}px` }),
    };
  }
}
