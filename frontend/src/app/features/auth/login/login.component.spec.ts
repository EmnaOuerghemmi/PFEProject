import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { LoginComponent } from './login.component';
import { AuthService } from '../../../core/services/auth.service';

/**
 * Parcours critique n°1 — connexion et redirection selon le rôle.
 *
 * Un candidat qui atterrirait sur le backoffice, ou un administrateur
 * renvoyé vers l'espace candidat, rendrait l'application inutilisable pour
 * une moitié des utilisateurs. Ce parcours couvre aussi l'enchaînement 2FA,
 * qui repose sur la reconnaissance d'un message d'erreur précis du backend :
 * si ce message change côté serveur, l'étape de saisie du code ne
 * s'afficherait plus et les comptes protégés deviendraient inaccessibles.
 */
describe('LoginComponent — parcours de connexion', () => {
  let fixture: ComponentFixture<LoginComponent>;
  let component: LoginComponent;
  let http: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    // AuthService restaure la session depuis localStorage à sa construction :
    // sans ce nettoyage, un jeton laissé par le test précédent déclenche un
    // appel /users/me supplémentaire et fausse les assertions sur le trafic.
    localStorage.clear();

    await TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
      imports: [LoginComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    fixture.detectChanges();
  });

  function connexionOk() {
    http.expectOne(r => r.url.endsWith('/auth/login'))
        .flush({ access_token: 'jwt', refresh_token: 'refresh' });
  }

  function profil(role: string) {
    http.expectOne(r => r.url.endsWith('/users/me'))
        .flush({ id: '1', email: 'a@b.tn', role });
  }

  function soumettre(email = 'a@b.tn', motDePasse = 'Secret123!') {
    component.email = email;
    component.password = motDePasse;
    component.login();
  }

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('refuse la soumission si un champ est vide', () => {
    component.email = '';
    component.password = '';
    component.login();

    expect(component.errorMessage).toContain('remplir');
    http.expectNone(r => r.url.endsWith('/auth/login'));
  });

  it('redirige un administrateur vers le backoffice', () => {
    soumettre();
    connexionOk();
    profil('ADMIN');

    expect(router.navigate).toHaveBeenCalledWith(['/admin']);
  });

  it('redirige un candidat vers l espace frontoffice', () => {
    soumettre();
    connexionOk();
    profil('CANDIDAT');

    expect(router.navigate).toHaveBeenCalledWith(['/frontoffice/home']);
  });

  it('bascule sur l etape 2FA quand le backend reclame un code', () => {
    soumettre();
    http.expectOne(r => r.url.endsWith('/auth/login')).flush(
      { detail: 'Code de double authentification requis.' },
      // 428, pas 401 : le serveur distingue « mot de passe faux » de
      // « second facteur manquant » par le statut, pour que le client n'ait
      // pas à reconnaître l'étape au texte du message.
      { status: 428, statusText: 'Precondition Required' },
    );

    expect(component.needsTotp).toBeTrue();
    // Les identifiants sont bons : afficher « identifiants invalides »
    // enverrait l'utilisateur corriger un mot de passe pourtant correct.
    expect(component.errorMessage).toBe('');
  });

  it('rejoue la connexion avec le code TOTP saisi', () => {
    soumettre();
    http.expectOne(r => r.url.endsWith('/auth/login')).flush(
      { detail: 'Code de double authentification requis.' },
      // 428, pas 401 : le serveur distingue « mot de passe faux » de
      // « second facteur manquant » par le statut, pour que le client n'ait
      // pas à reconnaître l'étape au texte du message.
      { status: 428, statusText: 'Precondition Required' },
    );

    component.totpCode = '123456';
    component.login();

    const seconde = http.expectOne(r => r.url.endsWith('/auth/login'));
    expect(seconde.request.body.totp_code).toBe('123456');
    seconde.flush({ access_token: 'jwt', refresh_token: 'refresh' });
    profil('ADMIN');

    expect(router.navigate).toHaveBeenCalledWith(['/admin']);
  });

  it('garde l utilisateur sur l etape 2FA si le code est faux', () => {
    component.needsTotp = true;
    component.totpCode = '000000';
    soumettre();

    http.expectOne(r => r.url.endsWith('/auth/login')).flush(
      { detail: 'Invalid 2FA code.' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(component.needsTotp).toBeTrue();
    expect(component.totpCode).toBe('');
    expect(component.errorMessage).toContain('incorrect');
  });

  it('affiche le message du serveur sur des identifiants invalides', () => {
    soumettre();
    http.expectOne(r => r.url.endsWith('/auth/login')).flush(
      { detail: 'Invalid credentials.' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(component.needsTotp).toBeFalse();
    expect(component.errorMessage).toBe('Invalid credentials.');
    expect(component.isLoading).toBeFalse();
  });

  it('ne transmet pas de champ totp_code lors d une connexion simple', () => {
    soumettre();
    const requete = http.expectOne(r => r.url.endsWith('/auth/login'));
    expect(requete.request.body.totp_code).toBeUndefined();
    requete.flush({ access_token: 'jwt' });
    profil('ADMIN');
  });

  it('stocke les jetons recus', () => {
    const auth = TestBed.inject(AuthService);
    const poserJeton = spyOn(auth, 'setToken');
    const poserRefresh = spyOn(auth, 'setRefreshToken');

    soumettre();
    http.expectOne(r => r.url.endsWith('/auth/login'))
        .flush({ access_token: 'jwt-abc', refresh_token: 'refresh-xyz' });
    profil('ADMIN');

    expect(poserJeton).toHaveBeenCalledWith('jwt-abc');
    expect(poserRefresh).toHaveBeenCalledWith('refresh-xyz');
  });
});
