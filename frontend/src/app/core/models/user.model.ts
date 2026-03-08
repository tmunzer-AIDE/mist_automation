export interface LoginRequest {
  email: string;
  password: string;
  remember_me: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserResponse {
  id: string;
  email: string;
  roles: string[];
  timezone: string;
  is_active: boolean;
  totp_enabled: boolean;
  created_at: string;
  last_login: string | null;
}

export interface UserCreate {
  email: string;
  password: string;
  roles: string[];
  timezone: string;
}

export interface UserUpdate {
  email?: string;
  roles?: string[];
  timezone?: string;
  is_active?: boolean;
}

export interface UserListResponse {
  users: UserResponse[];
  total: number;
}

export interface OnboardRequest {
  email: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}
