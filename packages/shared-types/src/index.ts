/**
 * Canonical data model types — provider-agnostic.
 * These mirror the Pydantic models in apps/api/app/models.py and are the
 * source of truth for what flows over the REST API.
 *
 * Class/interface names match the SQL table names one-to-one:
 *   Conversation ↔ conversations
 *   Message      ↔ messages
 *   File         ↔ files
 *   AuditLog     ↔ audit_log
 *   User         ↔ users
 *
 * Kept in sync manually with apps/api/app/models.py. Phase 6 will replace
 * this with auto-generation.
 */

export type UUID = string;

// ── Content blocks (stored in messages.content JSONB) ─────────────────────

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ImageBlock {
  type: "image";
  file_id: UUID;
}

export interface FileRefBlock {
  type: "file_ref";
  file_id: UUID;
  selection?: string | null;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: ContentBlock[];
  is_error: boolean;
}

export type ContentBlock =
  | TextBlock
  | ImageBlock
  | FileRefBlock
  | ToolUseBlock
  | ToolResultBlock;

// ── Enums ─────────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant" | "system";
export type EmbeddingStatus = "pending" | "done" | "failed";
export type ParseStatus = "pending" | "done" | "failed";

// ── Core entities ─────────────────────────────────────────────────────────

export interface User {
  id: UUID;
  clerk_id: string;
  email: string | null;
  created_at: string;
}

export interface Conversation {
  id: UUID;
  user_id: UUID;
  title: string | null;
  pinned_context: ContentBlock[];
  rolling_summary: string | null;
  summary_through_turn: number;
  extracted_facts: Record<string, unknown>;
  current_model: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Message {
  id: UUID;
  conversation_id: UUID;
  turn_index: number;
  role: MessageRole;
  content: ContentBlock[];
  model_used: string | null;
  /**
   * JSONB map keyed by provider id. Example: { "gemini": 142 }.
   * Never a single number — switch decisions are O(1) lookups by provider.
   */
  token_counts: Record<string, number> | null;
  cost_usd: string | null; // Decimal serialized as string
  embedding_status: EmbeddingStatus;
  idempotency_key: string | null;
  created_at: string;
}

export interface File {
  id: UUID;
  user_id: UUID;
  storage_url: string;
  mime_type: string | null;
  size_bytes: number | null;
  extracted_text: string | null;
  description: string | null;
  chunks: unknown[];
  parse_status: ParseStatus;
  original_filename?: string | null;
  error?: Record<string, unknown> | null;
  conversation_id?: UUID | null;
  created_at: string;
}

export interface FileUploadResponse {
  file_id: UUID;
  parse_status: ParseStatus;
  mime_type: string | null;
  original_filename: string | null;
  size_bytes: number | null;
}

export interface FileStatusResponse {
  file_id: UUID;
  parse_status: ParseStatus;
  mime_type: string | null;
  original_filename: string | null;
  size_bytes: number | null;
  has_description: boolean;
  has_extracted_text: boolean;
  chunk_count: number;
  error: Record<string, unknown> | null;
}

export interface AuditLog {
  id: number;
  user_id: UUID | null;
  action: string;
  resource_type: string | null;
  resource_id: UUID | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

// ── API shapes ────────────────────────────────────────────────────────────

export interface CreateConversationRequest {
  title?: string | null;
}

export interface CreateConversationResponse {
  conversation: Conversation;
}

export interface ListConversationsResponse {
  conversations: Conversation[];
  total: number;
}

export interface GetConversationResponse {
  conversation: Conversation;
  messages: Message[];
}

export interface SendMessageRequest {
  content: ContentBlock[];
  model?: string | null;
  idempotency_key?: string | null;
}

export interface UpdateConversationRequest {
  current_model?: string | null;
  title?: string | null;
}

export interface ModelInfo {
  id: string;
  provider: string;
}

export interface ModelListResponse {
  models: ModelInfo[];
  default: string;
}

export interface HealthResponse {
  status: "ok";
}

// ── SSE event payloads (server → client) ──────────────────────────────────

export interface ModelSwitchEvent {
  model: string;
  provider: string;
  note: string;
}

export interface ContextWarningEvent {
  dropped: number;
  message: string;
}

export type ChatStreamEvent =
  | { event: "user_message"; data: Message }
  | { event: "token"; data: { text: string } }
  | { event: "model_switch"; data: ModelSwitchEvent }
  | { event: "context_warning"; data: ContextWarningEvent }
  | { event: "done"; data: Message }
  | { event: "error"; data: { message: string } };
