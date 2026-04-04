export interface PasskeyResponse {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  transports: string[];
}

export interface PasskeyListResponse {
  passkeys: PasskeyResponse[];
  total: number;
}

export interface PasskeyRegisterBeginResponse {
  session_id: string;
  options: PublicKeyCredentialCreationOptionsJSON;
}

export interface PasskeyLoginBeginResponse {
  session_id: string;
  options: PublicKeyCredentialRequestOptionsJSON;
}
