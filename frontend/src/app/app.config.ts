import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter, withViewTransitions } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';

import { routes } from './app.routes';
import { jwtInterceptor } from './core/interceptors/jwt.interceptor';
import { errorInterceptor } from './core/interceptors/error.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    // View Transitions : fait glisser les panneaux hero/formulaire entre
    // /login et /register (voir les règles ::view-transition dans styles.css).
    provideRouter(routes, withViewTransitions()),
    // L'ordre compte : jwtInterceptor doit envelopper errorInterceptor pour
    // pouvoir intercepter un 401 et rejouer la requête après renouvellement du
    // jeton, sans qu'une notification d'erreur ne soit affichée entre-temps.
    provideHttpClient(withInterceptors([jwtInterceptor, errorInterceptor]))
  ]
};
