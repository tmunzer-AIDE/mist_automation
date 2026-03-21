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

export interface LlmConfig {
  id: string;
  name: string;
  provider: string;
  api_key_set: boolean;
  model: string | null;
  base_url: string | null;
  temperature: number;
  max_tokens_per_request: number;
  is_default: boolean;
  enabled: boolean;
}

export interface LlmConfigAvailable {
  id: string;
  name: string;
  provider: string;
  model: string | null;
  is_default: boolean;
}

export interface LlmModel {
  id: string;
  name: string;
}

export interface GlobalChatResponse {
  reply: string;
  thread_id: string;
  tool_calls: { tool: string; arguments: Record<string, unknown> }[];
  usage: Record<string, number>;
}

export interface McpConfig {
  id: string;
  name: string;
  url: string;
  headers_set: boolean;
  ssl_verify: boolean;
  enabled: boolean;
}

export interface McpConfigAvailable {
  id: string;
  name: string;
  url: string;
}

export interface McpTestResult {
  status: 'connected' | 'error';
  tools?: number;
  tool_names?: string[];
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
