"""Pydantic models — canonical, provider-agnostic data shapes.

These mirror the SQL tables one-to-one and are the source of truth for what
the REST API emits/accepts. TypeScript types in `packages/shared-types/src`
are kept in sync with these shapes by hand for Phase 1.

Naming: Pydantic class names match SQL table names exactly:
  Conversation ↔ conversations
  Message      ↔ messages
  File         ↔ files
  AuditLog     ↔ audit_log
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── ContentBlock variants ────────────────────────────────────────────────
# Stored inside `messages.content` as a JSONB array. Even pure-text messages
# are stored as `[{type: "text", text: "..."}]` — never as a plain string.


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    file_id: UUID


class FileRefBlock(BaseModel):
    type: Literal["file_ref"] = "file_ref"
    file_id: UUID
    selection: str | None = None


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list["ContentBlock"] = Field(default_factory=list)
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ImageBlock | FileRefBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]

ToolResultBlock.model_rebuild()


# ── Core entities ────────────────────────────────────────────────────────

MessageRole = Literal["user", "assistant", "system"]
EmbeddingStatus = Literal["pending", "done", "failed"]
ParseStatus = Literal["pending", "done", "failed"]


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    clerk_id: str
    email: str | None
    created_at: datetime


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    pinned_context: list[ContentBlock] = Field(default_factory=list)
    rolling_summary: str | None
    summary_through_turn: int
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    current_model: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    turn_index: int
    role: MessageRole
    content: list[ContentBlock]
    model_used: str | None
    # JSONB map keyed by provider — e.g. {"gemini": 142}. Never a single int.
    token_counts: dict[str, int] | None
    cost_usd: Decimal | None
    embedding_status: EmbeddingStatus
    idempotency_key: str | None
    created_at: datetime


class File(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    storage_url: str
    mime_type: str | None
    size_bytes: int | None
    extracted_text: str | None
    description: str | None
    chunks: list[Any] = Field(default_factory=list)
    parse_status: ParseStatus
    original_filename: str | None = None
    error: dict[str, Any] | None = None
    conversation_id: UUID | None = None
    created_at: datetime


class FileChunk(BaseModel):
    """One slice of a long document, stored verbatim inside files.chunks."""

    chunk_id: int
    text: str
    page: int | None = None


class AuditLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: UUID | None
    action: str
    resource_type: str | None
    resource_id: UUID | None
    metadata: dict[str, Any] | None
    created_at: datetime


# ── API request/response shapes ──────────────────────────────────────────


class CreateConversationRequest(BaseModel):
    title: str | None = None


class CreateConversationResponse(BaseModel):
    conversation: Conversation


class ListConversationsResponse(BaseModel):
    conversations: list[Conversation]
    total: int


class GetConversationResponse(BaseModel):
    conversation: Conversation
    messages: list[Message]


class SendMessageRequest(BaseModel):
    content: list[ContentBlock]
    model: str | None = None  # defaults to settings.default_model
    idempotency_key: str | None = None


# ── File API responses ──────────────────────────────────────────────────


class FileUploadResponse(BaseModel):
    """Returned by POST /files. The id is what goes into messages.content
    as {"type":"image","file_id": id} or {"type":"file_ref","file_id": id}.

    The client polls GET /files/{id} until `parse_status == 'done'`
    before sending the message. The chat UI shows a "processing" badge
    in the meantime but does not block submit.
    """

    file_id: UUID
    parse_status: ParseStatus
    mime_type: str | None
    original_filename: str | None
    size_bytes: int | None


class FileStatusResponse(BaseModel):
    file_id: UUID
    parse_status: ParseStatus
    mime_type: str | None
    original_filename: str | None
    size_bytes: int | None
    has_description: bool
    has_extracted_text: bool
    chunk_count: int
    error: dict[str, Any] | None
