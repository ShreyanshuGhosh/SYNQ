"""ProviderAdapter protocol — the single seam across providers.

This file is the contract from SYNQ_STRUCT §"Tier 7 — Provider Adapter".
Every provider (Anthropic, OpenAI, Gemini, self-hosted) implements this
exact protocol. The orchestrator only talks to these methods; it never
inspects the provider name. Anything provider-specific lives behind this
interface, never above it.

The five method signatures are FINAL after Phase 2. Later phases (Phase 3
multimodal, Phase 4 RAG, Phase 5 fallback) add capabilities but do not
change these signatures.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.models import Message

# ── Canonical StreamEvent ───────────────────────────────────────────────
# Every provider emits these five types. The adapter normalizes from each
# provider's wire format. The orchestrator handles them uniformly.

StreamEventType = Literal["text", "tool_use", "tool_use_delta", "stop", "error"]


@dataclass
class StreamEvent:
    type: StreamEventType
    content: str | dict[str, Any] | None = None
    # Final `stop` event carries provider-normalized token usage.
    usage: dict[str, int] | None = None


# ── Canonical translation request ───────────────────────────────────────
# The orchestrator hands the adapter this shape; the adapter does the
# wire-format translation. `system` is broken out separately because
# Anthropic and Gemini take it as a top-level parameter, while OpenAI
# takes it as a message with role="system".


@dataclass
class TranslationRequest:
    messages: list[Message]
    system: str | None = None
    model: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


# ── Validation result ───────────────────────────────────────────────────


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    # Some errors are recoverable (e.g. missing strict role alternation —
    # the adapter inserts a synthetic empty turn). `warnings` records what
    # was repaired. Hard failures go in `errors`.
    warnings: list[str] = field(default_factory=list)


# ── Provider capabilities ───────────────────────────────────────────────
# Used by `resolve_file` in each adapter to decide whether to embed raw
# image bytes or to substitute the cached text description. Per-model
# values per Phase 3 spec; defaults are pessimistic (no vision) so a
# new adapter without explicit flags degrades safely to text-only.


@dataclass
class ProviderCapabilities:
    vision: bool = False
    # Hard byte ceiling for inline (base64) images. Files larger than
    # this must take a different path — e.g. Gemini's Files API. Set to 0
    # to disable inline images entirely.
    max_image_mb: int = 0
    # True when the provider exposes a Files API for offloading large
    # binaries (currently only Gemini). The adapter handles the actual
    # upload + caching when this is set.
    supports_files_api: bool = False


# ── Resolved file payload ───────────────────────────────────────────────
# What `resolve_file` returns. The orchestrator embeds these into the
# canonical messages before the adapter translates to wire format.


@dataclass
class ResolvedFile:
    """Result of resolving a file_id for a specific target provider.

    Exactly one of {`inline_bytes`, `description_text`, `files_api_uri`}
    will be populated. The orchestrator inspects the populated field and
    constructs the appropriate provider-native block.
    """

    file_id: str
    mime_type: str | None
    # Used by replay tool & adapters when the target accepts raw bytes.
    inline_bytes: bytes | None = None
    # Substituted text when the target is text-only or the image is
    # missing. Joins extracted_text and description when both exist.
    description_text: str | None = None
    # Gemini Files API resource URI; set when supports_files_api=True.
    files_api_uri: str | None = None
    # Diagnostics for the replay tool.
    strategy: str = "unresolved"  # one of: inline | description | files_api | unresolved
    note: str = ""


# ── The Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class ProviderAdapter(Protocol):
    """The five-method contract. All async.

    Implementations:
      * apps/api/app/adapters/anthropic_adapter.py
      * apps/api/app/adapters/openai_adapter.py
      * apps/api/app/adapters/gemini_adapter.py
    """

    # Identity ──────────────────────────────────────────────────────────
    provider: str  # e.g. "anthropic", "openai", "gemini"
    # Context window for the active model in tokens. Used by the
    # orchestrator for naive Phase 2 truncation; Phase 4 replaces this
    # with intelligent compression.
    context_window: int
    # Per-model capability flags. Phase 3 uses `vision` + `max_image_mb`
    # to pick a `resolve_file` strategy.
    capabilities: ProviderCapabilities

    async def translate_messages(
        self,
        canonical: list[Message],
        resolved: dict[str, "ResolvedFile"] | None = None,
    ) -> dict[str, Any]:
        """Canonical messages -> provider wire-format payload.

        The result is a dict with provider-specific keys ("messages",
        "contents", "system", "systemInstruction", etc.). The orchestrator
        treats it as opaque and forwards it to `stream_completion`.

        `resolved` is the per-file lookup produced by
        `context_resolver.resolve_files_for_turn`. Phase 3 adapters use
        it to substitute ImageBlock / FileRefBlock with provider-native
        image parts (vision targets) or descriptive text (non-vision).
        When omitted, file blocks are dropped silently — matching the
        Phase 2 text-only behavior so Phase 2 callers keep working.
        """
        ...

    async def translate_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Canonical JSON Schema tool defs -> provider tool schema.

        Phase 2 stub: returns an empty dict when `tools` is empty. The full
        translation lands when tool calling ships in a later phase.
        """
        ...

    async def count_tokens(self, messages: list[Message]) -> int:
        """Token count for `messages` against this adapter's model.

        Implementations cache per (provider, content-hash) where possible
        (tiktoken is local; Anthropic/Gemini are network calls). The
        orchestrator caches the per-message result on
        `messages.token_counts` JSONB keyed by provider.
        """
        ...

    async def stream_completion(
        self, request: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion. `request` is the dict returned by
        `translate_messages` (possibly merged with tool translations).

        Yields canonical `StreamEvent`s. The terminal event MUST be
        either `stop` (with `usage` populated) or `error`. The adapter
        is responsible for normalizing every per-provider streaming
        quirk to this shape.
        """
        ...

    async def validate(self, request: dict[str, Any]) -> ValidationResult:
        """Pre-flight validation against provider rules.

        Checks role alternation, tool-result pairing, size limits, MIME
        compatibility. Returns errors (block send) or warnings (proceed
        but record). The orchestrator calls this before
        `stream_completion`.
        """
        ...

    async def resolve_file(self, file_row: Any) -> ResolvedFile:
        """Decide how a file should be rendered for THIS provider.

        Phase 3 strategy (per spec):
          * vision-capable target + image: inline bytes (base64) IF size
            fits ``capabilities.max_image_mb``, else Files API IF
            ``supports_files_api``, else fall back to description text.
          * non-vision target + image: substitute description / OCR text.
          * PDFs / DOCX / TXT / MD: substitute ``extracted_text`` (full
            for now — chunk-based RAG retrieval arrives in Phase 4).

        ``file_row`` is the SQLAlchemy `files` row (already
        authorization-checked by the caller).
        """
        ...
