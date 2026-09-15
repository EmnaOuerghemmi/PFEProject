import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';

export interface User {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface PaginatedUsers {
  total: number;
  page: number;
  size: number;
  items: User[];
}

export interface UserCreate {
  username: string;
  email: string;
  full_name: string;
  password: string;
  role: 'ADMIN' | 'RH' | 'RECRUTEUR' | 'CANDIDAT';
}

export interface UserUpdate {
  username?: string;
  email?: string;
  full_name?: string;
  role?: string;
  is_active?: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class UserManagementService {
  constructor(private apiService: ApiService) {}

  /**
   * Get paginated list of users with filters
   */
  getUsers(
    page: number = 1,
    size: number = 20,
    role?: string,
    isActive?: boolean,
    search?: string
  ): Observable<PaginatedUsers> {
    const params: Record<string, string | number | boolean> = {
      page,
      size
    };

    if (role) {
      params['role'] = role;
    }
    if (isActive !== undefined) {
      params['is_active'] = isActive;
    }
    if (search) {
      params['search'] = search;
    }

    return this.apiService.get<PaginatedUsers>('users', params);
  }

  /**
   * Get a specific user by ID
   */
  getUserById(userId: string): Observable<User> {
    return this.apiService.get<User>(`users/${userId}`);
  }

  /**
   * Create a new user
   */
  createUser(userData: UserCreate): Observable<User> {
    return this.apiService.post<User>('users', userData);
  }

  /**
   * Update a user (admin operation)
   */
  updateUser(userId: string, userData: UserUpdate): Observable<User> {
    return this.apiService.patch<User>(`users/${userId}`, userData);
  }

  /**
   * Delete a user (soft delete)
   */
  deleteUser(userId: string): Observable<void> {
    return this.apiService.delete<void>(`users/${userId}`);
  }

  /**
   * Get audit logs for users
   */
  getAuditLogs(page: number = 1, size: number = 50, userId?: string): Observable<any> {
    const params: Record<string, string | number> = {
      page,
      size
    };

    if (userId) {
      params['user_id'] = userId;
    }

    return this.apiService.get<any>('users/audit-logs', params);
  }
}
