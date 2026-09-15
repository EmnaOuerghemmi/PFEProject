import { Routes } from '@angular/router';

// Auth
import { LoginComponent } from './features/auth/login/login.component';
import { RegisterComponent } from './features/auth/register/register.component';
import { ForgotPasswordComponent } from './features/auth/forgot-password/forgot-password.component';
import { ResetPasswordComponent } from './features/auth/reset-password/reset-password.component';
import { VerifyEmailComponent } from './features/auth/verify-email/verify-email.component';

// Frontoffice
import { JobListComponent } from './features/frontoffice/job-list/job-list.component';
import { JobDetailComponent } from './features/frontoffice/job-detail/job-detail.component';
import { MyApplicationsComponent } from './features/frontoffice/my-applications/my-applications.component';
import { ProfileComponent } from './features/frontoffice/profile/profile.component';
import { SavedJobsComponent } from './features/frontoffice/saved-jobs/saved-jobs.component';
import { MainLayoutComponent } from './features/frontoffice/main-layout/main-layout.component';

// Home
import { HomeComponent } from './features/home/home.component';

// Public interview confirmation
import { InterviewConfirmComponent } from './features/interview-confirm/interview-confirm.component';

// Backoffice
import { BackofficeComponent }            from './features/backoffice/layout/backoffice.component';
import { JobsManagementComponent }        from './features/backoffice/jobs-management/jobs-management.component';
import { ApplicationsComponent }          from './features/backoffice/applications/applications.component';
import { UsersManagementComponent }       from './features/backoffice/users-management/users-management.component';
import { RecruitmentComponent }           from './features/backoffice/recruitment/recruitment.component';
import { CareerComponent }                from './features/backoffice/career/career.component';
import { NegotiationComponent }           from './features/backoffice/negotiation/negotiation.component';

// Guards
import { authGuard } from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';
import { permissionGuard } from './core/guards/permission.guard';

export const routes: Routes = [
  // ===== Root redirect =====
  // Le site carrière est la vitrine publique : un visiteur anonyme arrive sur
  // l'accueil, pas sur l'écran de connexion.
  { path: '', redirectTo: 'frontoffice/home', pathMatch: 'full' },

  // ===== Auth Routes (Public) =====
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },
  { path: 'forgot-password', component: ForgotPasswordComponent },
  { path: 'reset-password', component: ResetPasswordComponent },
  { path: 'verify-email', component: VerifyEmailComponent },

  // ===== Public Interview Confirmation =====
  { path: 'interview/confirm/:token', component: InterviewConfirmComponent },
  // Passage du test technique — page PUBLIQUE : le jeton tient lieu
  // d'authentification, comme pour la confirmation d'entretien.
  { path: 'test/:token',
    loadComponent: () => import('./features/assessment/test-run.component')
      .then(m => m.TestRunComponent) },

  // ===== Public Contract Signature (candidat, sans login) =====
  { path: 'contract/sign/:token',
    loadComponent: () => import('./features/contract-sign/contract-sign.component')
      .then(m => m.ContractSignComponent) },

  // ===== Frontoffice — site carrière PIQBIT =====
  // Le site est PUBLIC : un visiteur anonyme peut consulter l'accueil et les
  // offres. Seules les pages personnelles (candidatures, favoris, profil)
  // exigent une connexion — la postulation elle-même est protégée dans la page
  // de détail d'offre (invitation à se connecter).
  {
    path: 'frontoffice',
    component: MainLayoutComponent,
    children: [
      { path: '', redirectTo: 'home', pathMatch: 'full' },
      // ── Public (sans authentification) ──
      { path: 'home', component: HomeComponent },
      { path: 'jobs', component: JobListComponent },
      { path: 'job/:id', component: JobDetailComponent },
      // ── Espace personnel (authentification requise) ──
      { path: 'applications', component: MyApplicationsComponent, canActivate: [authGuard] },
      // Détail d'une candidature : comment le score a été construit. Le serveur
      // vérifie que la candidature appartient bien au demandeur — le garde
      // d'authentification ne suffirait pas.
      { path: 'application/:id',
        canActivate: [authGuard],
        loadComponent: () => import('./features/frontoffice/application-detail/application-detail.component')
          .then(m => m.ApplicationDetailComponent) },
      { path: 'saved-jobs', component: SavedJobsComponent, canActivate: [authGuard] },
      { path: 'profile', component: ProfileComponent, canActivate: [authGuard] }
    ]
  },

  // ===== Backoffice/Admin Routes (RH/Company only) =====
  // Each section has its own URL — bookmarkable, refresh-safe,
  // and the browser Back/Forward buttons work as expected.
  {
    path: 'admin',
    component: BackofficeComponent,
    canActivate: [adminGuard],
    children: [
      { path: '',            redirectTo: 'dashboard', pathMatch: 'full' },
      // Différé : le tableau de bord embarque chart.js. L'inclure au bundle
      // initial pénaliserait jusqu'au candidat qui ne verra jamais le
      // back-office — et celui-ci dépasse déjà son budget.
      { path: 'dashboard',
        loadComponent: () => import('./features/backoffice/dashboard/backoffice-dashboard.component')
          .then(m => m.BackofficeDashboardComponent) },
      { path: 'jobs',        component: JobsManagementComponent,
        canActivate: [permissionGuard('jobs', 'read')] },
      { path: 'applications',component: ApplicationsComponent,
        canActivate: [permissionGuard('applications', 'read')] },
      { path: 'users',       component: UsersManagementComponent,
        canActivate: [permissionGuard('users', 'read')] },
      // Fiche d'un utilisateur : son compte, et s'il est candidat son dossier,
      // ses candidatures et leurs scores.
      { path: 'users/:id',
        loadComponent: () => import('./features/backoffice/user-detail/user-detail.component')
          .then(m => m.UserDetailComponent),
        canActivate: [permissionGuard('users', 'read')] },
      { path: 'recruitment', component: RecruitmentComponent,
        canActivate: [permissionGuard('scoring', 'read')] },
      // Différée : la page embarque désormais le formulaire d'évaluation.
      // L'inclure au bundle initial la ferait payer à tout visiteur, candidat
      // compris — et celui-ci dépasse déjà son budget.
      { path: 'interviews',
        loadComponent: () => import('./features/backoffice/interview-manager/interview-manager.component')
          .then(m => m.InterviewManagerComponent),
        canActivate: [permissionGuard('interviews', 'read')] },
      { path: 'career',      component: CareerComponent,
        canActivate: [permissionGuard('career', 'read')] },
      { path: 'negotiation', component: NegotiationComponent,
        canActivate: [permissionGuard('negotiations', 'read')] },
      // Assistant CAG (chat extractif sourcé, sans LLM).
      { path: 'assistant',
        loadComponent: () => import('./features/backoffice/assistant/assistant.component')
          .then(m => m.AssistantComponent),
        canActivate: [permissionGuard('assistant', 'read')] },
      // Test technique : vivier de questions, envoi, relecture des réponses.
      { path: 'assessment',
        loadComponent: () => import('./features/backoffice/assessment/assessment.component')
          .then(m => m.AssessmentComponent),
        canActivate: [permissionGuard('assessment', 'read')] },
      // Gestion des contrats (onboarding).
      { path: 'contracts',
        loadComponent: () => import('./features/backoffice/contracts/contracts.component')
          .then(m => m.ContractsComponent),
        canActivate: [permissionGuard('contracts', 'read')] },
      // Modules Rapports & Décision en lazy-loading (préserve le bundle initial).
      { path: 'reports',
        loadComponent: () => import('./features/backoffice/reports/reports.component')
          .then(m => m.ReportsComponent),
        canActivate: [permissionGuard('reports', 'read')] },
      { path: 'decision',
        loadComponent: () => import('./features/backoffice/decision/decision.component')
          .then(m => m.DecisionComponent),
        canActivate: [permissionGuard('decision', 'read')] },
      // Modules Budget & Employés en lazy-loading (préserve le bundle initial).
      { path: 'budget',
        loadComponent: () => import('./features/budget/budget-dashboard/budget-dashboard.component')
          .then(m => m.BudgetDashboardComponent),
        canActivate: [permissionGuard('budget', 'read')] },
      { path: 'employees',
        loadComponent: () => import('./features/employees/employee-list/employee-list.component')
          .then(m => m.EmployeeListComponent),
        canActivate: [permissionGuard('employees', 'read')] },
      { path: 'employees/new',
        loadComponent: () => import('./features/employees/employee-form/employee-form.component')
          .then(m => m.EmployeeFormComponent),
        canActivate: [permissionGuard('employees', 'write')] },
      { path: 'employees/:id',
        loadComponent: () => import('./features/employees/employee-detail/employee-detail.component')
          .then(m => m.EmployeeDetailComponent),
        canActivate: [permissionGuard('employees', 'read')] },
      { path: 'employees/:id/edit',
        loadComponent: () => import('./features/employees/employee-form/employee-form.component')
          .then(m => m.EmployeeFormComponent),
        canActivate: [permissionGuard('employees', 'write')] },
    ],
  },

  // ===== Fallback =====
  { path: '**', redirectTo: '' }
];
