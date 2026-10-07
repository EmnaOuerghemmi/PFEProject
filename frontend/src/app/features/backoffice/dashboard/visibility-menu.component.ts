import { Component, ElementRef, EventEmitter, HostListener, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AUDIENCE_LABELS, Audience } from '../../../core/services/chart-series.service';

/**
 * L'œil d'une carte du tableau de bord : qui peut voir ce graphique.
 *
 * Affiché à l'administrateur seulement. Le choix est appliqué par le SERVEUR
 * (composition et données filtrées par rôle) — ce menu ne fait que le régler.
 */
@Component({
  selector: 'app-visibility-menu',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="vis">
      <button type="button" class="vis-btn" [class.vis-btn--restricted]="value !== 'ALL'"
              [class.vis-btn--locked]="verrouille" [disabled]="verrouille"
              (click)="basculer($event)" aria-haspopup="listbox" [attr.aria-expanded]="ouvert"
              [title]="'Visible par : ' + labels[value] + (verrouille ? ' — seul l’administrateur peut le modifier' : '')">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <ng-container *ngIf="value !== 'ADMIN'; else oeilBarre">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
          </ng-container>
          <ng-template #oeilBarre>
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
            <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
            <line x1="1" y1="1" x2="23" y2="23"/>
          </ng-template>
        </svg>
        <span class="vis-btn__label">{{ courts[value] }}</span>
        <svg *ngIf="verrouille" class="vis-btn__lock" width="11" height="11" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>
      </button>

      <ul class="vis-menu" *ngIf="ouvert" role="listbox" aria-label="Qui peut voir ce graphique ?"
          (click)="$event.stopPropagation()">
        <li class="vis-menu__title" role="presentation">Qui peut voir ce graphique ?</li>
        <li *ngFor="let a of audiences" role="option" class="vis-opt"
            [attr.aria-selected]="a === value" [class.vis-opt--on]="a === value"
            (click)="choisir(a)">
          <span class="vis-opt__label">{{ labels[a] }}</span>
          <small class="vis-opt__hint">{{ precisions[a] }}</small>
        </li>
      </ul>
    </div>
  `,
  styles: [`
    :host { display: inline-block; }
    .vis { position: relative; }
    .vis-btn {
      display: inline-flex; align-items: center; gap: 5px;
      height: 28px; padding: 0 9px;
      border: 1px solid var(--c-line-strong, #DACFB8); border-radius: var(--r-pill, 999px);
      background: var(--c-surface, #fff); color: var(--c-ink-soft, #3D4F4F);
      font: inherit; font-size: var(--fs-2xs, .7rem); font-weight: 700;
      cursor: pointer; transition: border-color .14s, background .14s, color .14s;
    }
    .vis-btn:hover { border-color: var(--c-gold, #10B981); }
    .vis-btn--restricted { background: var(--c-gold-soft, #D1FAE5); color: var(--c-gold-ink, #064E3B); border-color: transparent; }
    .vis-btn:focus-visible { outline: 2px solid var(--c-gold, #10B981); outline-offset: 2px; }
    /* Verrouillé : l'audience se lit, mais seul l'administrateur la change. */
    .vis-btn--locked, .vis-btn--locked:hover {
      opacity: .55; cursor: not-allowed; border-color: var(--c-line-strong, #DACFB8);
    }

    .vis-menu {
      position: absolute; z-index: 40; top: calc(100% + 6px); right: 0;
      min-width: 230px; margin: 0; padding: 6px; list-style: none;
      border: 1px solid var(--c-line-strong, #DACFB8); border-radius: 14px;
      background: var(--c-surface, #fff); box-shadow: 0 14px 32px rgba(6, 34, 42, .14);
    }
    .vis-menu__title {
      padding: 6px 10px 8px; font-size: var(--fs-2xs, .7rem); font-weight: 800;
      letter-spacing: .05em; text-transform: uppercase; color: var(--c-muted, #788888);
    }
    .vis-opt {
      display: flex; flex-direction: column; gap: 1px;
      padding: 8px 10px; border-radius: 9px; cursor: pointer;
    }
    .vis-opt:hover { background: var(--c-surface-2, #FBF8F1); }
    .vis-opt--on { background: var(--c-gold-soft, #D1FAE5); }
    .vis-opt__label { font-size: var(--fs-sm, .8125rem); font-weight: 700; color: var(--c-ink, #1B2B2B); }
    .vis-opt--on .vis-opt__label { color: var(--c-gold-ink, #064E3B); }
    .vis-opt__hint { font-size: var(--fs-2xs, .7rem); color: var(--c-muted, #788888); }
  `],
})
export class VisibilityMenuComponent {
  @Input() value: Audience = 'ALL';
  /** Affiché mais non cliquable : rôle sans droit de modifier le tableau de bord. */
  @Input() verrouille = false;
  @Output() valueChange = new EventEmitter<Audience>();

  readonly audiences: Audience[] = ['ALL', 'RH', 'RECRUTEUR', 'ADMIN'];
  readonly labels = AUDIENCE_LABELS;
  readonly courts: Record<Audience, string> = { ALL: 'Tous', RH: 'RH', RECRUTEUR: 'Recruteurs', ADMIN: 'Admin' };
  readonly precisions: Record<Audience, string> = {
    ALL: 'RH et recruteurs',
    RH: 'Les RH seulement',
    RECRUTEUR: 'Les recruteurs seulement',
    ADMIN: 'Masqué pour les autres rôles',
  };

  ouvert = false;

  constructor(private hote: ElementRef<HTMLElement>) {}

  basculer(evt: MouseEvent): void {
    evt.stopPropagation();
    if (this.verrouille) return;
    this.ouvert = !this.ouvert;
  }

  choisir(a: Audience): void {
    this.ouvert = false;
    if (a !== this.value) this.valueChange.emit(a);
  }

  @HostListener('document:click', ['$event'])
  surClicDocument(evt: MouseEvent): void {
    if (this.ouvert && !this.hote.nativeElement.contains(evt.target as Node)) this.ouvert = false;
  }

  @HostListener('keydown.escape')
  surEchap(): void { this.ouvert = false; }
}
