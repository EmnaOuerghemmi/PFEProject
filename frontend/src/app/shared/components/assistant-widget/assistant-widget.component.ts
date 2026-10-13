import {
  AfterViewChecked, Component, ElementRef, HostListener, OnInit, ViewChild, inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import {
  AssistantContexte, AssistantElement, AssistantReponse, CagService, CagSource,
} from '../../../core/services/cag.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  /** Lignes de résultat (offres, candidats, entretiens…), chacune vers sa page. */
  elements?: AssistantElement[];
  /** Relances proposées sous la réponse. */
  suggestions?: string[];
  confidence?: number | null;
  sources?: CagSource[];
}

/**
 * Assistant PIQBIT en bulle flottante, à la manière d'une messagerie.
 *
 * Il répond à partir des données de la plateforme, en direct (offres,
 * candidats, entretiens, tests…), sous les droits de la personne connectée,
 * et de la base de connaissances pour les questions de fonctionnement. Chaque
 * réponse propose des relances cliquables, et chaque résultat mène à sa page.
 *
 * Monté une seule fois dans le layout du back-office : il survit donc aux
 * changements de route, ce qui permet de garder la conversation ouverte en
 * naviguant d'une page à l'autre — y compris en suivant un de ses liens.
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

  /** Passe à true quand une réponse arrive alors que le panneau est fermé. */
  unread = false;

  /** Rappelé à chaque message : permet les relances (« et pour l'offre X ? »). */
  private contexte: AssistantContexte | null = null;
  private doitDefiler = false;

  ngOnInit(): void {
    this.messages.push({
      role: 'assistant',
      text: "Bonjour 👋 Je suis l'assistant PIQBIT. Je consulte vos données en direct — offres, "
          + 'candidats, entretiens, tests — et je réponds aux questions sur la plateforme. '
          + 'Posez-moi votre question, ou essayez :',
      suggestions: ["Vue d'ensemble", 'Entretiens à venir', 'Meilleurs candidats', 'Candidats en réserve'],
    });
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

    this.cag.message(texte, this.contexte).subscribe({
      next: (res: AssistantReponse) => {
        this.asking = false;
        this.doitDefiler = true;
        this.contexte = res.contexte;
        this.messages.push({
          role: 'assistant',
          text: res.reponse,
          elements: res.elements,
          suggestions: res.suggestions,
          confidence: res.confiance,
          sources: res.sources,
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

  /** Ouvre la page d'un résultat ; la conversation reste ouverte à côté. */
  ouvrir(e: AssistantElement): void {
    if (!e.lien) return;
    this.router.navigate([e.lien], { queryParams: e.parametres });
  }

  /** Les relances ne s'affichent que sous la dernière réponse : les anciennes sont dépassées. */
  estDerniere(i: number): boolean {
    return i === this.messages.length - 1 && !this.asking;
  }

  /** Ouvre la gestion de la base de connaissances et referme la bulle. */
  ouvrirBase(): void {
    this.fermer();
    this.router.navigate(['/admin/assistant'], { queryParams: { kb: 1 } });
  }

  confTone(c?: number | null): string {
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
