import { Routes } from '@angular/router';

// Toutes les pages sont chargées À LA DEMANDE (`loadComponent`).
//
// Importées ici, elles finissaient toutes dans le bundle initial : un visiteur
// de l'accueil téléchargeait le back-office entier — gestion des offres,
// classement, négociation — qu'il ne verra jamais. Chaque page est désormais un
// fichier à part, récupéré au moment où l'on y navigue.

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
  { path: 'login', loadComponent: () => import('./features/auth/login/login.component').then(m => m.LoginComponent) },
  { path: 'register', loadComponent: () => import('./features/auth/register/register.component').then(m => m.RegisterComponent) },
  { path: 'forgot-password', loadComponent: () => import('./features/auth/forgot-password/forgot-password.component').then(m => m.ForgotPasswordComponent) },
  { path: 'reset-password', loadComponent: () => import('./features/auth/reset-password/reset-password.component').then(m => m.ResetPasswordComponent) },
  { path: 'verify-email', loadComponent: () => import('./features/auth/verify-email/verify-email.component').then(m => m.VerifyEmailComponent) },

  // ===== Public Interview Confirmation =====
  { path: 'interview/confirm/:token', loadComponent: () => import('./features/interview-confirm/interview-confirm.component').then(m => m.InterviewConfirmComponent) },
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
    loadComponent: () => import('./features/frontoffice/main-layout/main-layout.component').then(m => m.MainLayoutComponent),
    children: [
      { path: '', redirectTo: 'home', pathMatch: 'full' },
      // ── Public (sans authentification) ──
      { path: 'home', loadComponent: () => import('./features/home/home.component').then(m => m.HomeComponent) },
      { path: 'jobs', loadComponent: () => import('./features/frontoffice/job-list/job-list.component').then(m => m.JobListComponent) },
      { path: 'job/:id', loadComponent: () => import('./features/frontoffice/job-detail/job-detail.component').then(m => m.JobDetailComponent) },
      // ── Espace personnel (authentification requise) ──
      { path: 'applications', loadComponent: () => import('./features/frontoffice/my-applications/my-applications.component').then(m => m.MyApplicationsComponent), canActivate: [authGuard] },
      // Détail d'une candidature : comment le score a été construit. Le serveur
      // vérifie que la candidature appartient bien au demandeur — le garde
      // d'authentification ne suffirait pas.
      { path: 'application/:id',
        canActivate: [authGuard],
        loadComponent: () => import('./features/frontoffice/application-detail/application-detail.component')
          .then(m => m.ApplicationDetailComponent) },
      { path: 'saved-jobs', loadComponent: () => import('./features/frontoffice/saved-jobs/saved-jobs.component').then(m => m.SavedJobsComponent), canActivate: [authGuard] },
      { path: 'profile', loadComponent: () => import('./features/frontoffice/profile/profile.component').then(m => m.ProfileComponent), canActivate: [authGuard] }
    ]
  },

  // ===== Backoffice/Admin Routes (RH/Company only) =====
  // Each section has its own URL — bookmarkable, refresh-safe,
  // and the browser Back/Forward buttons work as expected.
  {
    path: 'admin',
    loadComponent: () => import('./features/backoffice/layout/backoffice.component').then(m => m.BackofficeComponent),
    canActivate: [adminGuard],
    children: [
      { path: '',            redirectTo: 'dashboard', pathMatch: 'full' },
      // Différé : le tableau de bord embarque chart.js. L'inclure au bundle
      // initial pénaliserait jusqu'au candidat qui ne verra jamais le
      // back-office — et celui-ci dépasse déjà son budget.
      { path: 'dashboard',
        loadComponent: () => import('./features/backoffice/dashboard/backoffice-dashboard.component')
          .then(m => m.BackofficeDashboardComponent) },
      { path: 'jobs',        loadComponent: () => import('./features/backoffice/jobs-management/jobs-management.component').then(m => m.JobsManagementComponent),
        canActivate: [permissionGuard('jobs', 'read')] },
      { path: 'applications',loadComponent: () => import('./features/backoffice/applications/applications.component').then(m => m.ApplicationsComponent),
        canActivate: [permissionGuard('applications', 'read')] },
      { path: 'users',       loadComponent: () => import('./features/backoffice/users-management/users-management.component').then(m => m.UsersManagementComponent),
        canActivate: [permissionGuard('users', 'read')] },
      // Fiche d'un utilisateur : son compte, et s'il est candidat son dossier,
      // ses candidatures et leurs scores.
      { path: 'users/:id',
        loadComponent: () => import('./features/backoffice/user-detail/user-detail.component')
          .then(m => m.UserDetailComponent),
        canActivate: [permissionGuard('users', 'read')] },
      { path: 'recruitment', loadComponent: () => import('./features/backoffice/recruitment/recruitment.component').then(m => m.RecruitmentComponent),
        canActivate: [permissionGuard('scoring', 'read')] },
      // Différée : la page embarque désormais le formulaire d'évaluation.
      // L'inclure au bundle initial la ferait payer à tout visiteur, candidat
      // compris — et celui-ci dépasse déjà son budget.
      { path: 'interviews',
        loadComponent: () => import('./features/backoffice/interview-manager/interview-manager.component')
          .then(m => m.InterviewManagerComponent),
        canActivate: [permissionGuard('interviews', 'read')] },
      { path: 'negotiation', loadComponent: () => import('./features/backoffice/negotiation/negotiation.component').then(m => m.NegotiationComponent),
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
