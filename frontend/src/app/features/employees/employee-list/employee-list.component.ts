import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { EmployeeService } from '../../../core/services/employee.service';
import { Employee , EMPLOYEE_FIELD_LABELS } from '../../../core/models/employee.model';
import { ConfirmService } from '../../../core/services/confirm.service';

@Component({
  selector: 'app-employee-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './employee-list.component.html',
  styleUrls: ['./employee-list.component.css'],
})
export class EmployeeListComponent implements OnInit {
  private confirmService = inject(ConfirmService);

  employees: Employee[] = [];
  loading = true;
  error = '';

  departmentFilter = '';
  statusFilter = '';

  constructor(private employeeService: EmployeeService, private router: Router) {}

  ngOnInit(): void {
    this.loadEmployees();
  }

  loadEmployees(): void {
    this.loading = true;
    this.error = '';
    this.employeeService.getEmployees().subscribe({
      next: (data) => { this.employees = data; this.loading = false; },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail || 'Impossible de charger les employés.';
      },
    });
  }

  get departments(): string[] {
    return [...new Set(this.employees.map(e => e.department).filter(Boolean))].sort();
  }

  get filtered(): Employee[] {
    return this.employees.filter(e =>
      (!this.departmentFilter || e.department === this.departmentFilter) &&
      (!this.statusFilter || e.status === this.statusFilter)
    );
  }

  get activeCount(): number {
    return this.employees.filter(e => e.status === 'active').length;
  }

  open(employee: Employee): void {
    this.router.navigate(['/admin/employees', employee.id]);
  }

  async remove(employee: Employee, event: Event): Promise<void> {
    event.stopPropagation();
    const ok = await this.confirmService.askDelete(
      `Supprimer la fiche de ${employee.firstName} ${employee.lastName} ?`
    );
    if (!ok) return;
    this.employeeService.deleteEmployee(employee.id).subscribe({
      next: () => this.loadEmployees(),
      error: () => { this.error = 'Suppression impossible.'; },
    });
  }

  statusLabel(s: string): string {
    return ({ active: 'Actif', inactive: 'Inactif', 'on-leave': 'En congé' } as any)[s] || s;
  }

  trackEmp(_i: number, e: Employee): string { return e.id; }

  /** Les champs manquants en toutes lettres — l'API renvoie ses clés. */
  champsManquants(e: Employee): string {
    const noms = (e.missingFields ?? [])
      .map((c) => EMPLOYEE_FIELD_LABELS[c] || c);
    return noms.length ? 'À compléter : ' + noms.join(', ') : '';
  }
}
