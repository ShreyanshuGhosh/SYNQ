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

    async def translate_messages(self, canonical: list[Message]) -> dict[str, Any]:
        """Canonical messages -> provider wire-format payload.

        The result is a dict with provider-specific keys ("messages",
        "contents", "system", "systemInstruction", etc.). The orchestrator
        treats it as opaque and forwards it to `stream_completion`.
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
