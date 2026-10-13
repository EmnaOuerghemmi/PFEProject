import { Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule, registerLocaleData } from '@angular/common';
import localeFr from '@angular/common/locales/fr';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ContractService, PublicContract } from '../../core/services/contract.service';

// Dates de la page en français (« 12 octobre 2026 ») : sans cette locale, Angular
// n'affiche que l'anglais. Enregistrée ici car la page est chargée à la demande.
registerLocaleData(localeFr);

@Component({
  selector: 'app-contract-sign',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contract-sign.component.html',
  styleUrls: ['./contract-sign.component.css'],
})
export class ContractSignComponent implements OnInit, OnDestroy {
  /**
   * Le cadre de signature n'existe qu'une fois le contrat chargé (`*ngIf`).
   * Il était préparé UNE fois, dans un `setTimeout`, à un moment où il n'était
   * pas toujours encore dans la page : le contexte de dessin restait vide et
   * chaque tracé était ignoré en silence. Le préparer quand Angular le crée
   * (ce setter) supprime cette course.
   *
   * Angular rappelle aussi ce setter avec le MÊME cadre dès qu'un bloc `*ngIf`
   * apparaît ou disparaît (fenêtre de lecture du contrat, dialogue de refus).
   * Le recalibrer alors l'effaçait — redimensionner un canvas le vide — sans
   * que `hasDrawn` change : le candidat signait avec une image vide.
   */
  @ViewChild('pad') set pad(ref: ElementRef<HTMLCanvasElement> | undefined) {
    if (ref?.nativeElement === this.canvas) return;
    this.observateur?.disconnect();
    this.canvas = ref?.nativeElement;
    this.ctx = undefined;
    if (!this.canvas) return;
    this.preparerCadre();
    // Si la fenêtre change de taille (rotation du téléphone), le cadre est
    // reconstruit à la bonne résolution sans perdre le tracé.
    if (typeof ResizeObserver !== 'undefined') {
      this.observateur = new ResizeObserver(() => this.preparerCadre());
      this.observateur.observe(this.canvas);
    }
  }

  token = '';
  contract: PublicContract | null = null;
  loading = true;
  error = '';

  // Formulaire de signature
  signerName = '';
  /** Le candidat atteste avoir lu le contrat — ne se coche qu'après l'avoir ouvert. */
  aLu = false;
  consent = false;
  submitting = false;
  hasDrawn = false;

  // Lecture du contrat complet (PDF dans une fenêtre)
  lectureOuverte = false;
  lectureEnCours = false;
  lectureErreur = '';
  /** Le contrat a été ouvert au moins une fois : condition pour cocher « j'ai lu ». */
  contratOuvert = false;
  pdfUrl: SafeResourceUrl | null = null;
  private pdfObjectUrl: string | null = null;

  // Refus
  showDecline = false;
  declineReason = '';

  private canvas?: HTMLCanvasElement;
  private ctx?: CanvasRenderingContext2D;
  private observateur?: ResizeObserver;
  private drawing = false;

  constructor(
    private route: ActivatedRoute,
    private contracts: ContractService,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    this.token = this.route.snapshot.paramMap.get('token') || '';
    this.contracts.getPublic(this.token).subscribe({
      next: (c) => {
        this.contract = c;
        this.signerName = c.candidate_name;
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail || 'Contrat introuvable ou lien expiré.';
      },
    });
  }

  ngOnDestroy(): void {
    this.observateur?.disconnect();
    this.libererPdf();
  }

  // ── Lecture du contrat complet ──────────────────────────────────────────────

  ouvrirLecture(): void {
    this.lectureOuverte = true;
    this.lectureErreur = '';
    if (this.pdfUrl) { this.contratOuvert = true; return; }   // déjà chargé : on le rouvre
    this.lectureEnCours = true;
    this.contracts.getPublicPdf(this.token).subscribe({
      next: (blob) => {
        this.pdfObjectUrl = URL.createObjectURL(blob);
        this.pdfUrl = this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfObjectUrl);
        this.contratOuvert = true;
        this.lectureEnCours = false;
      },
      error: () => {
        this.lectureEnCours = false;
        this.lectureErreur = 'Le contrat n\'a pas pu être chargé. Réessayez dans un instant.';
      },
    });
  }

  fermerLecture(): void { this.lectureOuverte = false; }

  private libererPdf(): void {
    if (this.pdfObjectUrl) URL.revokeObjectURL(this.pdfObjectUrl);
    this.pdfObjectUrl = null;
    this.pdfUrl = null;
  }

  get isSignable(): boolean {
    return this.contract?.status === 'SENT';
  }

  // ── Cadre de signature ──────────────────────────────────────────────────────

  /** (Re)calibre la résolution du cadre sur sa taille affichée, en gardant le tracé. */
  private preparerCadre(): void {
    const canvas = this.canvas;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;   // pas encore mis en page : l'observateur rappellera

    const tracePrecedente = this.hasDrawn && this.ctx ? canvas.toDataURL('image/png') : null;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.lineWidth = 2.2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#111827';
    this.ctx = ctx;

    if (tracePrecedente) {
      const image = new Image();
      image.onload = () => ctx.drawImage(image, 0, 0, rect.width, rect.height);
      image.src = tracePrecedente;
    }
  }

  /** La résolution du cadre correspond-elle à sa taille affichée ? */
  private calibre(canvas: HTMLCanvasElement): boolean {
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    return Math.abs(canvas.width - Math.round(rect.width * ratio)) <= 1
        && Math.abs(canvas.height - Math.round(rect.height * ratio)) <= 1;
  }

  private position(e: PointerEvent): { x: number; y: number } {
    const rect = this.canvas!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  startDraw(e: PointerEvent): void {
    // Le cadre est préparé à la demande si le premier calibrage a eu lieu avant
    // la mise en page : le tracé ne doit jamais dépendre de ce détail.
    if (this.canvas && (!this.ctx || !this.calibre(this.canvas))) this.preparerCadre();
    if (!this.ctx || !this.canvas) return;
    e.preventDefault();
    this.canvas.setPointerCapture?.(e.pointerId);   // le trait continue même hors du cadre
    this.drawing = true;
    const { x, y } = this.position(e);
    this.ctx.beginPath();
    this.ctx.moveTo(x, y);
  }

  moveDraw(e: PointerEvent): void {
    if (!this.drawing || !this.ctx) return;
    e.preventDefault();
    const { x, y } = this.position(e);
    this.ctx.lineTo(x, y);
    this.ctx.stroke();
    this.hasDrawn = true;
  }

  endDraw(): void { this.drawing = false; }

  clearPad(): void {
    if (this.canvas && this.ctx) {
      this.ctx.save();
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this.ctx.restore();
    }
    this.hasDrawn = false;
  }

  // ── Actions ─────────────────────────────────────────────────────────────────

  /** Le cadre ne contient aucun trait, quoi qu'en dise `hasDrawn`. */
  private cadreVide(canvas: HTMLCanvasElement): boolean {
    const ctx = canvas.getContext('2d');
    if (!ctx || !canvas.width || !canvas.height) return true;
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) return false;
    return true;
  }

  sign(): void {
    if (!this.canSubmit || !this.canvas) return;
    // Dernier garde-fou : on vérifie l'image elle-même, pas seulement l'état
    // du formulaire — un cadre vidé par erreur ne doit jamais devenir une signature.
    if (this.cadreVide(this.canvas)) {
      this.hasDrawn = false;
      this.error = "Votre signature n'apparaît plus dans le cadre : signez à nouveau.";
      return;
    }
    const dataUrl = this.canvas.toDataURL('image/png');
    this.submitting = true;
    this.error = '';
    this.contracts.sign(this.token, {
      signer_name: this.signerName.trim(),
      signature_image: dataUrl,
      consent: this.consent,
    }).subscribe({
      next: (c) => { this.contract = c; this.submitting = false; },
      error: (err) => {
        this.submitting = false;
        this.error = err?.error?.detail || 'La signature a échoué. Réessayez.';
      },
    });
  }

  get canSubmit(): boolean {
    return this.isSignable && !this.submitting
        && this.signerName.trim().length >= 2 && this.aLu && this.consent && this.hasDrawn;
  }

  /** Ce qui empêche encore de signer, dit en clair — le bouton grisé seul n'explique rien. */
  get manque(): string[] {
    const reste: string[] = [];
    if (!this.aLu) reste.push(this.contratOuvert ? 'la case « j\'ai lu le contrat »' : 'la lecture du contrat complet');
    if (this.signerName.trim().length < 2) reste.push('votre nom');
    if (!this.hasDrawn) reste.push('votre signature dans le cadre');
    if (!this.consent) reste.push('la case d\'accord');
    return reste;
  }

  confirmDecline(): void {
    this.submitting = true;
    this.contracts.decline(this.token, this.declineReason.trim()).subscribe({
      next: (c) => { this.contract = c; this.submitting = false; this.showDecline = false; },
      error: (err) => {
        this.submitting = false;
        this.error = err?.error?.detail || 'Action impossible.';
      },
    });
  }

  typeLabel(t?: string): string {
    return ({ CDI: 'CDI', CDD: 'CDD', STAGE: 'Stage', ALTERNANCE: 'Alternance' } as any)[t || ''] || t;
  }
}
