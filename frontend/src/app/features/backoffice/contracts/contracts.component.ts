import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  ContractService, Contract, ContractStats, PendingContract, StatutApresRetrait,
} from '../../../core/services/contract.service';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';
import { PermissionsService } from '../../../core/services/permissions.service';
import { SelectComponent, SelectOption } from '../../../shared/components/select/select.component';
import {
  ChoixCorrection, CorrectionAdminComponent,
} from '../../../shared/components/correction-admin/correction-admin.component';

@Component({
  selector: 'app-contracts',
  standalone: true,
  imports: [CommonModule, FormsModule, SelectComponent, CorrectionAdminComponent],
  templateUrl: './contracts.component.html',
  styleUrls: ['./contracts.component.css'],
})
export class ContractsComponent implements OnInit {
  private toast = inject(ToastService);
  private confirmService = inject(ConfirmService);
  private permissions = inject(PermissionsService);

  // ── Retrait d'un contrat (administrateur) ─────────────────────────────────
  /** Contrat dont la fenêtre de retrait est ouverte. */
  aRetirer: Contract | null = null;
  retraitEnCours = false;
  erreurRetrait = '';
  readonly choixApresRetrait: ChoixCorrection[] = [
    { value: 'ACCEPTED', label: 'Acceptée — contrat à refaire' },
    { value: 'ON_HOLD', label: 'En réserve' },
    { value: 'REJECTED', label: 'Rejetée' },
  ];

  /** Retirer un contrat envoyé, signé ou actif : réservé à l'administrateur. */
  get peutRetirer(): boolean { return this.permissions.peut('contracts', 'delete'); }

  contracts: Contract[] = [];
  stats: ContractStats | null = null;
  loading = true;
  error = '';
  statusFilter = '';

  /**
   * Candidats acceptés sans contrat, reçus avec leurs informations et un
   * salaire proposé que le RH confirme (ou corrige) avant la création.
   */
  pending: PendingContract[] = [];
  pendingSalary: Record<string, number | null> = {};
  creatingId: string | null = null;

  // Édition inline du brouillon
  editing: Contract | null = null;
  editModel: Partial<Contract> = {};
  saving = false;

  copiedId: string | null = null;
  downloadingId: string | null = null;
  sendingId: string | null = null;

  /** Options des sélecteurs — des champs, pas des getters (voir SelectComponent). */
  readonly typeOptions: SelectOption[] = ['CDI', 'CDD', 'STAGE', 'ALTERNANCE'].map(t => ({ value: t, label: t }));
  readonly civilityOptions: SelectOption[] = [
    { value: '', label: '— À renseigner —' },
    { value: 'M.', label: 'M.' },
    { value: 'Mme', label: 'Mme' },
  ];
  readonly statusOptions: SelectOption[] = [
    { value: '', label: 'Tous les statuts' },
    { value: 'DRAFT', label: 'Brouillon' },
    { value: 'SENT', label: 'Envoyé' },
    { value: 'SIGNED', label: 'Signé' },
    { value: 'ACTIVE', label: 'Actif' },
    { value: 'DECLINED', label: 'Refusé' },
    { value: 'EXPIRED', label: 'Expiré' },
  ];

  constructor(private contractsSvc: ContractService) {}

  ngOnInit(): void {
    this.load();
    this.loadPending();
  }

  load(): void {
    this.loading = true;
    this.error = '';
    this.contractsSvc.list(this.statusFilter || undefined).subscribe({
      next: (rows) => { this.contracts = rows; this.loading = false; },
      error: (err) => { this.loading = false; this.error = err?.error?.detail || 'Chargement impossible.'; },
    });
    this.contractsSvc.stats().subscribe({ next: (s) => (this.stats = s) });
  }

  setStatusFilter(value: string): void {
    this.statusFilter = value;
    this.load();
  }

  // ── Candidats acceptés à contractualiser ───────────────────────────────────
  loadPending(): void {
    this.contractsSvc.pending().subscribe({
      next: (rows) => {
        this.pending = rows;
        // Le salaire proposé pré-remplit le champ ; le RH le confirme ou le corrige.
        this.pendingSalary = Object.fromEntries(rows.map(p => [p.application_id, p.suggested_salary]));
      },
    });
  }

  /** Crée le brouillon avec le salaire confirmé, puis ouvre l'édition pour l'identité. */
  confirmPending(p: PendingContract): void {
    const salary = this.pendingSalary[p.application_id];
    if (!salary || salary <= 0) return;
    this.creatingId = p.application_id;
    this.contractsSvc.createFromApplication(p.application_id, { contract_type: 'CDI', salary }).subscribe({
      next: (created) => {
        this.creatingId = null;
        this.toast.success(`Contrat créé pour ${p.candidate_name} — complétez son identité avant l'envoi.`);
        this.loadPending();
        this.contractsSvc.list(this.statusFilter || undefined).subscribe({
          next: (rows) => {
            this.contracts = rows;
            const nouveau = rows.find(c => c.id === created.id);
            if (nouveau) this.startEdit(nouveau);
          },
        });
        this.contractsSvc.stats().subscribe({ next: (s) => (this.stats = s) });
      },
      error: (err) => {
        this.creatingId = null;
        this.toast.fromHttpError(err, 'Création du contrat impossible.');
      },
    });
  }

  salarySourceLabel(source: PendingContract['salary_source']): string {
    return ({
      negotiation: 'Montant négocié',
      expected_salary: 'Prétention du candidat',
      offer_max: "Maximum de l'offre",
      offer_min: "Minimum de l'offre",
    } as Record<string, string>)[source || ''] || 'À saisir';
  }

  /**
   * Champs d'identité encore vides : le contrat les écrit en toutes lettres
   * (civilité, naissance, CIN, adresse) et la date d'entrée fixe l'article 3.
   */
  missingFields(c: Contract): string[] {
    const manquants: string[] = [];
    if (!c.employee_civility) manquants.push('civilité');
    if (!c.employee_birth_date) manquants.push('date de naissance');
    if (!c.employee_cin) manquants.push('CIN');
    if (!c.employee_cin_issue_date) manquants.push('date de délivrance de la CIN');
    if (!c.employee_address) manquants.push('adresse');
    if (!c.start_date) manquants.push("date d'entrée");
    return manquants;
  }

  // ── Édition brouillon ───────────────────────────────────────────────────────
  startEdit(c: Contract): void {
    this.editing = c;
    this.editModel = {
      contract_type: c.contract_type, position: c.position, department: c.department,
      salary: c.salary, trial_period_months: c.trial_period_months, weekly_hours: c.weekly_hours,
      start_date: c.start_date ? (c.start_date.slice(0, 10) as any) : null,
      notes: c.notes,
      employee_civility: c.employee_civility,
      employee_birth_date: c.employee_birth_date ? (c.employee_birth_date.slice(0, 10) as any) : null,
      employee_cin: c.employee_cin,
      employee_cin_issue_date: c.employee_cin_issue_date ? (c.employee_cin_issue_date.slice(0, 10) as any) : null,
      employee_address: c.employee_address,
    };
  }
  cancelEdit(): void { this.editing = null; this.editModel = {}; }

  saveEdit(): void {
    if (!this.editing) return;
    this.saving = true;
    // Une civilité vide n'est pas envoyée : le serveur n'accepte que « M. » / « Mme ».
    const payload = { ...this.editModel, employee_civility: this.editModel.employee_civility || null };
    this.contractsSvc.update(this.editing.id, payload).subscribe({
      next: () => { this.saving = false; this.cancelEdit(); this.load(); },
      error: (err) => { this.saving = false; this.error = err?.error?.detail || 'Enregistrement impossible.'; },
    });
  }

  // ── Actions ─────────────────────────────────────────────────────────────────
  async send(c: Contract): Promise<void> {
    const manquants = c.status === 'DRAFT' ? this.missingFields(c) : [];
    if (manquants.length) {
      const ok = await this.confirmService.ask({
        title: 'Contrat incomplet',
        message: `Ces informations seront laissées en blanc dans le contrat : ${manquants.join(', ')}. Envoyer quand même ?`,
        confirmLabel: 'Envoyer quand même',
      });
      if (!ok) return;
    }
    this.sendingId = c.id;
    this.contractsSvc.send(c.id).subscribe({
      next: () => {
        this.sendingId = null;
        this.toast.success('Contrat envoyé au candidat par e-mail.');
        this.load();
      },
      error: (err) => { this.sendingId = null; this.toast.fromHttpError(err, "L'envoi a échoué."); },
    });
  }

  copyLink(c: Contract): void {
    if (!c.public_url) return;
    navigator.clipboard?.writeText(c.public_url).then(() => {
      this.copiedId = c.id;
      setTimeout(() => { if (this.copiedId === c.id) this.copiedId = null; }, 2500);
    });
  }

  downloadPdf(c: Contract): void {
    this.downloadingId = c.id;
    this.contractsSvc.downloadPdf(c.id).subscribe({
      next: (blob) => {
        this.downloadingId = null;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `Contrat_PIQBIT_${(c.candidate_name || 'candidat').replace(/\s+/g, '_')}.pdf`;
        a.click(); URL.revokeObjectURL(url);
      },
      error: () => { this.downloadingId = null; },
    });
  }

  async remove(c: Contract): Promise<void> {
    const ok = await this.confirmService.askDelete(
      `Supprimer ce contrat brouillon pour ${c.candidate_name} ?`
    );
    if (!ok) return;
    this.contractsSvc.remove(c.id).subscribe({ next: () => { this.load(); this.loadPending(); } });
  }

  messageRetrait(c: Contract): string {
    const signe = c.status === 'ACTIVE' || c.status === 'SIGNED';
    return `Le contrat de ${c.candidate_name} (${this.statusLabel(c.status).toLowerCase()}) sera supprimé`
      + (signe ? ", et la fiche employé créée à sa signature passera « Inactif ». Rien d'autre n'est effacé." : '.')
      + ' La candidature reprend le statut choisi ci-dessous.';
  }

  ouvrirRetrait(c: Contract): void {
    this.aRetirer = c;
    this.erreurRetrait = '';
  }

  confirmerRetrait(e: { choix: string; motif: string }): void {
    const c = this.aRetirer;
    if (!c || this.retraitEnCours) return;
    this.retraitEnCours = true;
    this.erreurRetrait = '';
    this.contractsSvc.retirer(c.id, e.motif, e.choix as StatutApresRetrait).subscribe({
      next: (r) => {
        this.retraitEnCours = false;
        this.aRetirer = null;
        this.toast.success(r.employe_desactive
          ? 'Contrat retiré — la fiche employé est passée « Inactif ».'
          : 'Contrat retiré.');
        this.load();
        this.loadPending();
      },
      error: (err) => {
        this.retraitEnCours = false;
        this.erreurRetrait = err?.error?.detail || 'Le retrait a échoué.';
      },
    });
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────
  statusLabel(s: string): string {
    return ({ DRAFT: 'Brouillon', SENT: 'Envoyé', SIGNED: 'Signé', ACTIVE: 'Actif',
              DECLINED: 'Refusé', EXPIRED: 'Expiré' } as any)[s] || s;
  }
  statusTone(s: string): string {
    return ({ DRAFT: 'muted', SENT: 'info', SIGNED: 'success', ACTIVE: 'success',
              DECLINED: 'danger', EXPIRED: 'warn' } as any)[s] || 'muted';
  }
  trackC(_i: number, c: Contract): string { return c.id; }
  trackP(_i: number, p: PendingContract): string { return p.application_id; }
}
