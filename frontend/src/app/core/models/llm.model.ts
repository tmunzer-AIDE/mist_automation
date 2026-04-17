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
  context_window_tokens: number | null;
  context_window_effective: number;
  is_default: boolean;
  enabled: boolean;
  canvas_prompt_tier: string | null;
  canvas_prompt_tier_effective: string;
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
  context_window?: number | null;
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
  headers: Record<string, string> | null;
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
  metadata?: { tool_calls?: { tool: string; server: string; status: string; arguments?: Record<string, unknown>; result_preview?: string }[]; thinking_texts?: string[] } | null;
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
  compacted: boolean;
  context_window_tokens: number | null;
  context_tokens_estimate: number | null;
  context_usage_percent: number | null;
  compressed_messages: number;
  compression_ratio: number | null;
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
  mcp_config_id: string | null;
  effective_mcp_config_id: string | null;
  error: string | null;
  last_synced_at: string | null;
}

export interface SkillGitRepo {
  id: string;
  url: string;
  branch: string;
  token_set: boolean;
  mcp_config_id: string | null;
  local_path: string;
  last_refreshed_at: string | null;
  error: string | null;
}

export type ArtifactType = 'code' | 'markdown' | 'html' | 'mermaid' | 'svg' | 'chart';

export interface Artifact {
  id: string;
  type: ArtifactType;
  title: string;
  language?: string;
  content: string;
}

export interface ParsedContent {
  prose: string;
  artifacts: Artifact[];
}

export interface MemoryEntry {
  id: string;
  key: string;
  value: string;
  category: string;
  source_thread_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryListResponse {
  entries: MemoryEntry[];
  total: number;
}

export interface ConsolidationLogSummary {
  id: string;
  user_id: string;
  user_email: string;
  run_at: string;
  entries_before: number;
  entries_after: number;
  actions_summary: { merged: number; deleted: number; kept: number };
  llm_model: string;
  llm_tokens_used: number;
}

export interface ConsolidationLogDetail {
  id: string;
  user_id: string;
  run_at: string;
  entries_before: number;
  entries_after: number;
  actions: Record<string, unknown>[];
  llm_model: string;
  llm_tokens_used: number;
}

export interface MemoryStats {
  total_entries: number;
  users_with_memories: number;
  avg_entries_per_user: number;
  top_users: { user_id: string; count: number }[];
}
