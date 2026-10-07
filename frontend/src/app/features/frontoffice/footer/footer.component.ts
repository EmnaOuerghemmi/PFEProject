import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-footer',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './footer.component.html',
  styleUrls: ['./footer.component.css'],
})
export class FooterComponent {
  /**
   * L'année était écrite en dur dans le gabarit (« © 2026 »). Un pied de page
   * figé finit toujours par mentir, et personne ne s'en aperçoit avant un
   * client.
   */
  readonly annee = new Date().getFullYear();
}
