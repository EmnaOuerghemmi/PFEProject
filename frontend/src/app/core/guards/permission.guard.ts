import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';
import { PermissionsService } from '../services/permissions.service';

/**
 * Garde de route par permission.
 *
 * `adminGuard` ne dit que « cette personne appartient au back-office » : une
 * fois cette porte franchie, TOUTES les pages s'ouvraient, y compris celles
 * dont l'API refuse ensuite les données. Un recruteur atterrissait sur la
 * gestion des utilisateurs ou le budget, voyait la page se dessiner, puis un
 * écran vide — un 403 déguisé en bug.
 *
 * Cette garde referme chaque page sur la permission qu'elle exige réellement,
 * et renvoie vers le tableau de bord plutôt que vers la connexion : la
 * personne EST légitimement connectée, elle n'a simplement rien à faire ici.
 *
 * Ce n'est pas une mesure de sécurité — c'est de la lisibilité. La protection
 * reste côté serveur, sur chaque requête.
 */
export const permissionGuard = (ressource: string, action: string): CanActivateFn => {
  return () => {
    const permissions = inject(PermissionsService);
    const router = inject(Router);

    return permissions.peutAsync(ressource, action).pipe(
      map(autorise => autorise ? true : router.createUrlTree(['/admin/dashboard'])),
    );
  };
};
