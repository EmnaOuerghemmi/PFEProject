import { Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  CagService, CagAnswer, CagSource, CagStatus, KnowledgeEntry,
} from '../../../core/services/cag.service';
import { ConfirmService } from '../../../core/services/confirm.service';

interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  confidence?: number;
  sources?: CagSource[];
  fromCache?: boolean;
  lowConfidence?: boolean;
}

@Component({
  selector: 'app-assistant',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './assistant.component.html',
  styleUrls: ['./assistant.component.css'],
})
export class AssistantComponent implements OnInit {
  private confirmService = inject(ConfirmService);

  // Chat
  messages: ChatMessage[] = [];
  question = '';
  asking = false;

  status: CagStatus | null = null;

  suggestions = [
    'Comment se déroule un entretien ?',
    'Combien de temps pour recevoir une réponse ?',
    "Qu'est-ce que le score IA ?",
    'Comment protégez-vous mes données ?',
  ];

  // Base de connaissances
  showKb = false;
  entries: KnowledgeEntry[] = [];
  kbLoading = false;
  newEntry = { title: '', content: '', category: 'AUTRE', source: '' };
  categories = ['RECRUTEMENT', 'ENTRETIEN', 'CANDIDATURE', 'PROCESS', 'POLITIQUE', 'AUTRE'];
  saving = false;

  private route = inject(ActivatedRoute);

  constructor(private cag: CagService) {}

  ngOnInit(): void {
    // La bulle flottante assure désormais la conversation sur toutes les pages ;
    // cette page sert surtout à administrer la base de connaissances. Le widget
    // y renvoie avec `?kb=1` pour ouvrir directement le bon onglet.
    if (this.route.snapshot.queryParamMap.get('kb') === '1') {
      this.showKb = true;
      this.loadKb();
    }
    this.cag.getStatus().subscribe({ next: (s) => (this.status = s) });
    this.messages.push({
      role: 'assistant',
      text: "Bonjour 👋 Je suis l'assistant PIQBIT. Je réponds à partir de la base de "
          + "connaissances RH — mes réponses sont extraites de documents réels, "
          + 'jamais inventées. Posez-moi une question.',
    });
  }

  ask(q?: string): void {
    const text = (q ?? this.question).trim();
    if (!text || this.asking) return;

    this.messages.push({ role: 'user', text });
    this.question = '';
    this.asking = true;

    this.cag.ask(text).subscribe({
      next: (res: CagAnswer) => {
        this.asking = false;
        this.messages.push({
          role: 'assistant',
          text: res.answer,
          confidence: res.confidence,
          sources: res.sources,
          fromCache: res.from_cache,
          lowConfidence: res.sources.length === 0,
        });
      },
      error: () => {
        this.asking = false;
        this.messages.push({ role: 'assistant', text: "Une erreur est survenue. Réessayez." });
      },
    });
  }

  confTone(c?: number): string {
    if (c == null) return 'muted';
    if (c >= 40) return 'high';
    if (c >= 20) return 'mid';
    return 'low';
  }

  // ── Base de connaissances ──────────────────────────────────────────────────

  toggleKb(): void {
    this.showKb = !this.showKb;
    if (this.showKb && !this.entries.length) this.loadKb();
  }

  loadKb(): void {
    this.kbLoading = true;
    this.cag.listKnowledge().subscribe({
      next: (rows) => { this.entries = rows; this.kbLoading = false; },
      error: () => { this.kbLoading = false; },
    });
  }

  addEntry(): void {
    if (!this.newEntry.title.trim() || this.newEntry.content.trim().length < 10) return;
    this.saving = true;
    this.cag.addKnowledge({
      title: this.newEntry.title.trim(),
      content: this.newEntry.content.trim(),
      category: this.newEntry.category,
      source: this.newEntry.source.trim() || undefined,
    }).subscribe({
      next: () => {
        this.saving = false;
        this.newEntry = { title: '', content: '', category: 'AUTRE', source: '' };
        this.loadKb();
        this.cag.getStatus().subscribe({ next: (s) => (this.status = s) });
      },
      error: () => { this.saving = false; },
    });
  }

  async deleteEntry(e: KnowledgeEntry): Promise<void> {
    const ok = await this.confirmService.askDelete(
      `Supprimer « ${e.title} » de la base de connaissances ?`
    );
    if (!ok) return;
    this.cag.deleteKnowledge(e.id).subscribe({ next: () => this.loadKb() });
  }

  trackMsg(i: number): number { return i; }
  trackEntry(_i: number, e: KnowledgeEntry): string { return e.id; }
}
