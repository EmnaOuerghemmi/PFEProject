# Captures d'écran du rapport

Déposer ici les fichiers PNG, **avec exactement les noms ci-dessous**. Le mode
opératoire complet (où aller, ce qui doit être visible, ce qui doit être
masqué) est dans `report/06_screenshot_plan.md`.

## Règles non négociables

1. **Jeu de démonstration uniquement** — `python backend/scripts/seed_demo.py`.
   Comptes en `@piqbit.demo`, mot de passe `Demo1234!`.
   Ne jamais capturer un écran alimenté par `backend/uploads/` : ce répertoire
   contient 264 CV réels.
2. **Aucun jeton visible** dans une barre d'URL (`/interview/confirm/…`,
   `/test/…`, `/contract/sign/…`) — recadrer sous la barre d'adresse.
3. **Aucun secret TOTP réel**, aucune clé d'API, aucun chemin de poste de
   travail, aucune notification système dans le cadre.
4. Fenêtre à **1440 px**, zoom **100 %**, thème clair.

## Liste des fichiers attendus

### Parcours candidat — 6
- [ ] `job_list_public.png`
- [ ] `job_detail_apply.png`
- [ ] `my_applications_status.png`
- [ ] `application_score_detail.png`
- [ ] `interview_confirm_public.png`
- [ ] `test_public_session.png`

### Parcours recruteur et RH — 10
- [ ] `recruitment_ranking.png`
- [ ] `cv_analysis_breakdown.png`
- [ ] `semantic_search_results.png`
- [ ] `interview_manager_slots.png`
- [ ] `interview_scheduler_recruiter.png`
- [ ] `assessment_review.png`
- [ ] `salary_prediction_form.png`
- [ ] `negotiation_live_log.png`
- [ ] `contract_sign_certificate.png`
- [ ] `cag_assistant_sources.png`

### RH interne et pilotage — 6
- [ ] `employees_list.png`
- [ ] `budget_department.png`
- [ ] `career_plan.png`
- [ ] `reports_snapshot.png`
- [ ] `decision_board.png`
- [ ] `notifications_realtime.png`

### Administration — 3
- [ ] `backoffice_dashboard.png`
- [ ] `users_management_roles.png`
- [ ] `audit_log_trail.png`

### Sécurité — 3
- [ ] `2fa_totp_enrollment.png`
- [ ] `rbac_denied_403.png`
- [ ] `account_lockout.png`

### Livraison et exécution — 5
- [ ] `ci_workflow_summary.png`
- [ ] `ci_test_failure_detail.png`
- [ ] `docker_compose_healthy.png`
- [ ] `health_endpoint.png`
- [ ] `bundle_budget_warning.png`

**Total : 28 captures.**

## Insertion dans le rapport

```latex
\pqscreenshot{recruitment_ranking}{Classement des candidats pour une offre.}{fig:recruitment_ranking}
```

Le nom est donné **sans extension** : `\graphicspath` inclut déjà ce
répertoire.
