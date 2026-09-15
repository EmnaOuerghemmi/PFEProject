import {
  AfterViewChecked, Component, ElementRef, HostListener, OnInit, ViewChild, inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { CagService, CagAnswer, CagSource, CagStatus } from '../../../core/services/cag.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  confidence?: number;
  sources?: CagSource[];
  fromCache?: boolean;
  lowConfidence?: boolean;
}

/**
 * Assistant PIQBIT en bulle flottante, à la manière d'une messagerie.
 *
 * Monté une seule fois dans le layout du back-office : il survit donc aux
 * changements de route, ce qui permet de garder la conversation ouverte en
 * naviguant d'une page à l'autre — le comportement attendu d'une messagerie,
 * et la raison pour laquelle il n'est pas rendu par le `router-outlet`.
 *
 * La gestion de la base de connaissances reste sur sa page dédiée
 * (`/admin/assistant`), réservée au RH : elle n'a pas sa place dans une bulle
 * de conversation, mais l'en-tête du panneau y donne accès en un clic.
 */
@Component({
  selector: 'app-assistant-widget',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './assistant-widget.component.html',
  styleUrls: ['./assistant-widget.component.css'],
})
export class AssistantWidgetComponent implements OnInit, AfterViewChecked {
  private cag = inject(CagService);
  private router = inject(Router);

  @ViewChild('log') private logRef?: ElementRef<HTMLElement>;
  @ViewChild('field') private fieldRef?: ElementRef<HTMLInputElement>;

  open = false;
  messages: ChatMessage[] = [];
  question = '';
  asking = false;
  status: CagStatus | null = null;

  /** Passe à true quand une réponse arrive alors que le panneau est fermé. */
  unread = false;

  private doitDefiler = false;

  suggestions = [
    'Comment se déroule un entretien ?',
    'Combien de temps pour recevoir une réponse ?',
    "Qu'est-ce que le score IA ?",
    'Comment protégez-vous mes données ?',
  ];

  ngOnInit(): void {
    this.messages.push({
      role: 'assistant',
      text: "Bonjour 👋 Je suis l'assistant PIQBIT. Je réponds à partir de la base de "
          + 'connaissances RH — mes réponses sont extraites de documents réels, '
          + 'jamais inventées. Posez-moi une question.',
    });
    // Le statut n'est pas indispensable à la conversation : une erreur ici ne
    // doit pas empêcher d'ouvrir la bulle.
    this.cag.getStatus().subscribe({ next: (s) => (this.status = s), error: () => {} });
  }

  ngAfterViewChecked(): void {
    if (this.doitDefiler) {
      this.doitDefiler = false;
      this.defilerEnBas();
    }
  }

  basculer(): void {
    this.open = !this.open;
    if (this.open) {
      this.unread = false;
      this.doitDefiler = true;
      // Le panneau vient d'apparaître : on attend le rendu pour donner le focus.
      setTimeout(() => this.fieldRef?.nativeElement.focus(), 80);
    }
  }

  fermer(): void {
    this.open = false;
  }

  /** Échap ferme le panneau — convention attendue d'une boîte de dialogue. */
  @HostListener('document:keydown.escape')
  surEchap(): void {
    if (this.open) this.fermer();
  }

  ask(q?: string): void {
    const texte = (q ?? this.question).trim();
    if (!texte || this.asking) return;

    this.messages.push({ role: 'user', text: texte });
    this.question = '';
    this.asking = true;
    this.doitDefiler = true;

    this.cag.ask(texte).subscribe({
      next: (res: CagAnswer) => {
        this.asking = false;
        this.doitDefiler = true;
        this.messages.push({
          role: 'assistant',
          text: res.answer,
          confidence: res.confidence,
          sources: res.sources,
          fromCache: res.from_cache,
          lowConfidence: res.sources.length === 0,
        });
        if (!this.open) this.unread = true;
      },
      error: () => {
        this.asking = false;
        this.doitDefiler = true;
        this.messages.push({
          role: 'assistant',
          text: 'Une erreur est survenue. Réessayez dans un instant.',
        });
      },
    });
  }

  /** Ouvre la gestion de la base de connaissances et referme la bulle. */
  ouvrirBase(): void {
    this.fermer();
    this.router.navigate(['/admin/assistant'], { queryParams: { kb: 1 } });
  }

  confTone(c?: number): string {
    if (c == null) return 'muted';
    if (c >= 40) return 'high';
    if (c >= 20) return 'mid';
    return 'low';
  }

  trackMsg(i: number): number { return i; }

  private defilerEnBas(): void {
    const el = this.logRef?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }
}
