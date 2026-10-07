import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

declare global {
  interface Window {
    google: {
      accounts: {
        id: {
          initialize: (config: any) => void;
          renderButton: (element: HTMLElement, options: any) => void;
          getCredential?: () => string;
          cancel?: () => void;
        };
      };
    };
  }
}

@Injectable({
  providedIn: 'root'
})
export class GoogleService {
  private googleClientId = ''; // Will be set from environment
  private credentialResponse$ = new Subject<string>();
  public credentialResponse = this.credentialResponse$.asObservable();
  private isInitialized = false;

  constructor() {}

  /**
   * Insère le SDK Google (`accounts.google.com/gsi/client`) la première fois
   * qu'une page en a besoin.
   *
   * Il était chargé depuis index.html, donc sur TOUTES les pages — avec ses
   * cookies tiers et ses requêtes vers Google, même pour un visiteur qui ne se
   * connecte jamais. Seule la page de connexion l'utilise.
   */
  private chargerSdk(): void {
    if (document.querySelector('script[data-google-gsi]')) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.dataset['googleGsi'] = '';
    document.head.appendChild(script);
  }

  /**
   * Résout dès que le SDK Google est disponible. On sonde `window.google`
   * plutôt que d'écouter l'événement `load` du script : le `<script>` peut déjà
   * être chargé (navigation SPA) au moment où l'on s'abonne.
   */
  private whenGoogleReady(): Promise<boolean> {
    return new Promise((resolve) => {
      if (typeof window === 'undefined') { resolve(false); return; }
      if (window.google?.accounts?.id) { resolve(true); return; }
      this.chargerSdk();

      const start = Date.now();
      const timer = setInterval(() => {
        if (window.google?.accounts?.id) {
          clearInterval(timer);
          resolve(true);
        } else if (Date.now() - start > 15000) {
          // 15 s : réseau lent / SDK bloqué. On abandonne sans casser la page
          // (le formulaire e-mail / mot de passe reste utilisable).
          clearInterval(timer);
          resolve(false);
        }
      }, 120);
    });
  }

  private initializeGoogle(): void {
    if (this.isInitialized || !this.googleClientId) return;
    if (typeof window === 'undefined' || !window.google?.accounts?.id) return;

    window.google.accounts.id.initialize({
      client_id: this.googleClientId,
      callback: (response: any) => this.handleCredentialResponse(response),
      auto_select: false,
      cancel_on_tap_outside: true,
    });
    this.isInitialized = true;
  }

  async renderButton(elementId: string, opts: { iconOnly?: boolean } = {}): Promise<void> {
    if (typeof window === 'undefined') return;

    const ready = await this.whenGoogleReady();
    if (!ready || !this.googleClientId) return;

    // Le conteneur peut ne pas encore être dans le DOM (rendu Angular en cours) :
    // on le laisse quelques instants apparaître avant d'abandonner.
    let element = document.getElementById(elementId);
    for (let i = 0; !element && i < 25; i++) {
      await new Promise((r) => setTimeout(r, 120));
      element = document.getElementById(elementId);
    }
    if (!element) return;

    this.initializeGoogle();
    if (!this.isInitialized) return;

    element.innerHTML = '';
    if (opts.iconOnly) {
      window.google.accounts.id.renderButton(element, {
        type: 'icon',
        shape: 'circle',
        theme: 'outline',
        size: 'large',
      });
    } else {
      window.google.accounts.id.renderButton(element, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        shape: 'pill',
        locale: 'fr',
        logo_alignment: 'left',
        width: Math.min(Math.max(element.clientWidth || 320, 200), 400),
      });
    }
  }

  private handleCredentialResponse(response: any): void {
    if (response.credential) {
      this.credentialResponse$.next(response.credential);
    }
  }

  setClientId(clientId: string): void {
    if (this.googleClientId !== clientId) {
      this.googleClientId = clientId;
      this.isInitialized = false;
      this.initializeGoogle();
    }
  }
}
