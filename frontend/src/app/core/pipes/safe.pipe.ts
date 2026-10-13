import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

/**
 * Autorise une URL dans un `<iframe>` — uniquement un aperçu local `blob:`.
 *
 * Toutes les prévisualisations (CV) passent par `URL.createObjectURL()` sur un
 * fichier téléchargé avec le jeton de l'utilisateur. Contourner l'assainissement
 * d'Angular pour N'IMPORTE QUELLE URL ferait de ce pipe une porte ouverte au
 * XSS si une adresse venue de l'API ou d'un paramètre y passait un jour : tout
 * ce qui n'est pas un `blob:` de cette origine est remplacé par une page vide.
 */
@Pipe({
  name: 'safe',
  standalone: true
})
export class SafePipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}

  transform(url: string): SafeResourceUrl {
    const sur = estBlobLocal(url) ? url : 'about:blank';
    // Seule une URL `blob:` créée par cette page atteint cette ligne (vérifiée ci-dessus).
    return this.sanitizer.bypassSecurityTrustResourceUrl(sur); // nosemgrep: typescript.angular.security.audit.angular-domsanitizer.angular-bypasssecuritytrust
  }
}

/** `blob:` de la même origine que l'application — produit par `URL.createObjectURL`. */
export function estBlobLocal(url: string | null | undefined): boolean {
  return !!url && url.startsWith(`blob:${window.location.origin}/`);
}
