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

export interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
  metadata?: { tool_calls?: { tool: string; server: string; status: string; result_preview?: string }[]; thinking_texts?: string[] } | null;
  timestamp?: string;
}

export interface LlmUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ConversationThreadSummary {
  id: string;
  feature: string;
  context_ref: string | null;
  message_count: number;
  preview: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationThreadDetail {
  id: string;
  feature: string;
  context_ref: string | null;
  messages: ChatMessage[];
  mcp_config_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ConversationThreadListResponse {
  threads: ConversationThreadSummary[];
  total: number;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  source: 'direct' | 'git';
  enabled: boolean;
  git_repo_id: string | null;
  git_repo_url: string | null;
  error: string | null;
  last_synced_at: string | null;
}

export interface SkillGitRepo {
  id: string;
  url: string;
  branch: string;
  token_set: boolean;
  local_path: string;
  last_refreshed_at: string | null;
  error: string | null;
}
