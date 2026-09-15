import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { UserManagementService, User, UserCreate } from '../../../core/services/user-management.service';
import { ToastService } from '../../../core/services/toast.service';
import { ConfirmService } from '../../../core/services/confirm.service';

@Component({
  selector: 'app-users-management',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './users-management.component.html',
  styleUrls: ['./users-management.component.css']
})
export class UsersManagementComponent implements OnInit {
  private toast = inject(ToastService);
  private confirmService = inject(ConfirmService);

  // Data
  allUsers: User[] = [];
  filteredUsers: User[] = [];
  paginatedUsers: User[] = [];

  // Filters
  searchQuery = '';
  selectedRole = '';
  sortBy = 'created_at';

  // Pagination
  currentPage = 1;
  pageSize = 10;
  totalPages = 1;
  totalUsers = 0;

  // Loading state
  isLoading = false;
  errorMessage = '';

  // Modal
  showModal = false;
  editingUser: User | null = null;
  formData = this.getEmptyForm();

  constructor(private userService: UserManagementService) {}

  ngOnInit(): void {
    this.loadUsers();
  }

  loadUsers(): void {
    this.isLoading = true;
    this.errorMessage = '';

    // Call the backend API with filters
    let role = this.selectedRole || undefined;
    let search = this.searchQuery || undefined;


    this.userService.getUsers(this.currentPage, this.pageSize, role, undefined, search).subscribe({
      next: (response) => {
        this.allUsers = response.items;
        this.totalUsers = response.total;
        this.totalPages = Math.ceil(response.total / this.pageSize);
        this.updatePaginatedUsers();
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Error loading users:', error);
        console.error('Error status:', error.status);
        console.error('Error message:', error.message);
        console.error('Error body:', error.error);

        let errorMsg = 'Erreur lors du chargement des utilisateurs';

        if (error.status === 0) {
          errorMsg = 'Impossible de se connecter au serveur. Vérifiez que le backend est en cours d\'exécution sur http://localhost:3000';
        } else if (error.status === 401) {
          errorMsg = 'Non authentifié. Veuillez vous reconnecter';
        } else if (error.status === 403) {
          errorMsg = 'Vous n\'avez pas les permissions pour accéder à cette ressource';
        } else if (error.status === 404) {
          errorMsg = 'Endpoint non trouvé';
        } else if (error.error?.detail) {
          errorMsg = error.error.detail;
        }

        this.errorMessage = errorMsg;
        this.isLoading = false;
      }
    });
  }

  filterUsers(): void {
    this.currentPage = 1;
    this.loadUsers();
  }

  sortUsers(): void {
    // Sorting is done on the backend by passing the search/role parameters
    this.currentPage = 1;
    this.loadUsers();
  }

  updatePaginatedUsers(): void {
    this.paginatedUsers = this.allUsers;
  }

  nextPage(): void {
    if (this.currentPage < this.totalPages) {
      this.currentPage++;
      this.loadUsers();
    }
  }

  previousPage(): void {
    if (this.currentPage > 1) {
      this.currentPage--;
      this.loadUsers();
    }
  }

  getRoleLabel(role: string): string {
    const labels: { [key: string]: string } = {
      'ADMIN': 'Administrateur',
      'RH': 'RH',
      'RECRUTEUR': 'Recruteur',
      'CANDIDAT': 'Candidat'
    };
    return labels[role] || role;
  }

  formatDate(date: string): string {
    return new Date(date).toLocaleDateString('fr-FR');
  }

  openAddUserModal(): void {
    this.editingUser = null;
    this.formData = this.getEmptyForm();
    this.showModal = true;
  }

  editUser(user: User): void {
    this.editingUser = user;
    this.formData = { ...user, password: '' } as any;
    this.showModal = true;
  }

  saveUser(): void {
    if (!this.formData.full_name || !this.formData.email || !this.formData.username) {
      this.toast.warning('Veuillez remplir tous les champs obligatoires.');
      return;
    }

    if (this.editingUser) {
      // Update existing user
      this.userService.updateUser(this.editingUser.id, {
        full_name: this.formData.full_name,
        email: this.formData.email,
        username: this.formData.username,
        role: this.formData.role,
        is_active: this.formData.is_active
      }).subscribe({
        next: () => {
          this.toast.success('Utilisateur mis à jour.');
          this.closeModal();
          this.loadUsers();
        },
        error: (error) => {
          this.toast.fromHttpError(error, "Impossible de mettre à jour l'utilisateur.");
        }
      });
    } else {
      // Create new user
      if (!this.formData.password) {
        this.toast.warning('Saisissez un mot de passe pour le nouvel utilisateur.');
        return;
      }

      this.userService.createUser(this.formData as UserCreate).subscribe({
        next: () => {
          this.toast.success('Utilisateur créé.');
          this.closeModal();
          this.loadUsers();
        },
        error: (error) => {
          this.toast.fromHttpError(error, "Impossible de créer l'utilisateur.");
        }
      });
    }
  }

  async deleteUser(user: User): Promise<void> {
    const ok = await this.confirmService.askDelete(
      `Supprimer définitivement le compte de ${user.full_name} ? Cette action est irréversible.`
    );
    if (ok) {
      this.userService.deleteUser(user.id).subscribe({
        next: () => {
          this.toast.success('Utilisateur supprimé.');
          this.loadUsers();
        },
        error: (error) => {
          this.toast.fromHttpError(error, "Impossible de supprimer l'utilisateur.");
        }
      });
    }
  }

  closeModal(): void {
    this.showModal = false;
    this.editingUser = null;
    this.formData = this.getEmptyForm();
  }

  getEmptyForm() {
    return {
      full_name: '',
      email: '',
      username: '',
      role: 'CANDIDAT',
      password: '',
      is_active: true
    };
  }
}
