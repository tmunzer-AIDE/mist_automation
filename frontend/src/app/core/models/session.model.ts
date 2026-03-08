export interface DeviceInfo {
  browser: string | null;
  os: string | null;
  ip_address: string;
  user_agent: string | null;
}

export interface UserSession {
  id: string;
  user_id: string;
  device_info: DeviceInfo;
  trusted_device: boolean;
  created_at: string;
  last_activity: string;
  expires_at: string;
  is_current?: boolean;
}

export interface SessionListResponse {
  sessions: UserSession[];
  total: number;
}

export interface PasswordPolicy {
  min_length: number;
  require_uppercase: boolean;
  require_lowercase: boolean;
  require_digits: boolean;
  require_special_chars: boolean;
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
  is_initialized: boolean;
  password_policy?: PasswordPolicy;
}
