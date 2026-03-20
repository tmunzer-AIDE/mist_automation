export interface LlmStatus {
  enabled: boolean;
  provider: string | null;
  model: string | null;
}

export interface LlmTestResult {
  status: 'connected' | 'error';
  model?: string;
  response?: string;
  error?: string;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
  timestamp?: string;
}

export interface LlmUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}
