export type UserRole = 'ADMIN' | 'RH' | 'RECRUTEUR' | 'CANDIDAT';

export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  phone_number: string | null;
  avatar_url: string | null;
  ministry: string | null;
  department: string | null;
  job_title: string | null;
  employee_id: string | null;
  language: 'fr' | 'ar';
  timezone: string;
  role: UserRole;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  permissions: Record<string, any> | null;
  totp_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface PaginatedUsers {
  total: number;
  page: number;
  size: number;
  items: User[];
}

export interface UserUpdate {
  full_name?: string;
  phone_number?: string;
  avatar_url?: string;
  ministry?: string;
  department?: string;
  job_title?: string;
  language?: 'fr' | 'ar';
  timezone?: string;
  notification_preferences?: Record<string, any>;
}

export interface UserAdminUpdate extends UserUpdate {
  role?: UserRole;
  is_active?: boolean;
  is_verified?: boolean;
  permissions?: Record<string, any>;
}

export interface UserCreate {
  email: string;
  username: string;
  password: string;
  full_name?: string;
  phone_number?: string;
  ministry?: string;
  department?: string;
  job_title?: string;
  employee_id?: string;
  language?: 'fr' | 'ar';
  timezone?: string;
  role?: UserRole;
}
