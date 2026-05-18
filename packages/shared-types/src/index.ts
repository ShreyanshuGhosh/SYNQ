/**
 * Canonical data model types — provider-agnostic.
 * These mirror the Pydantic models in apps/api/app/ and are the source
 * of truth for what flows over the REST API.
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
  selection?: string; // e.g. "pages 3-7"
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
export type MessageStatus = "complete" | "interrupted" | "pending";

// ── Core entities ─────────────────────────────────────────────────────────

export interface Conversation {
  id: UUID;
  user_id: UUID;
  title: string | null;
  pinned_context: ContentBlock[];
  rolling_summary: string | null;
  summary_through_turn: number;
  extracted_facts: Record<string, unknown>;
  current_model: string | null;
  version: number; // optimistic concurrency
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
  token_counts: Record<string, number> | null; // keyed by provider id
  cost_usd: number | null;
  embedding_status: EmbeddingStatus;
  status: MessageStatus;
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
  created_at: string;
}

// ── API shapes ────────────────────────────────────────────────────────────

export interface CreateConversationRequest {
  title?: string;
}

export interface CreateConversationResponse {
  conversation: Conversation;
}

export interface ListConversationsResponse {
  conversations: Conversation[];
  total: number;
}

export interface HealthResponse {
  status: "ok";
}
