"""Turn orchestrator — provider-agnostic.

This module owns the turn lifecycle described in ARCHITECTURE §"Tier 4 —
Orchestrator":

    validate -> build context -> call provider -> stream -> persist

CRITICAL CONSTRAINT (carried over from Phase 2):
    NO provider-specific conditionals live here. The only thing this
    module knows is "give me an adapter for this model id, then call the
    protocol methods." If a future change requires `if provider ==
    "anthropic"` here, that branch belongs in an adapter instead.

Phase 4 changes:
  * Naive `_truncate_oldest` is replaced with the six-part compression
    assembly in ``context_engine.build_context``.
  * Identity-drift handling moves into the context engine (which owns
    every system-frame message). Detection still happens here so the
    SSE generator can emit a `model_switch` event before tokens flow.
  * Pinned context, extracted facts, and rolling summary are pulled
    from the ``conversations`` row and handed to the engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.adapters import ProviderAdapter, adapter_for, provider_for
from app.adapters.base import ResolvedFile, StreamEvent
from app.context_engine import BuiltContext, build_context
from app.context_resolver import resolve_files_for_turn
from app.core.logging import get_logger
from app.core.tracing import get_tracer, set_attributes
from app.db import SessionLocal
from app.models import FileRefBlock, ImageBlock, Message

log = get_logger(__name__)
logger = log  # back-compat
_tracer = get_tracer("app.orchestrator")


def _content_flags(messages: list[Message]) -> tuple[bool, bool]:
    """Quick scan: does the message list contain image or file blocks?"""
    has_images = False
    has_files = False
    for m in messages:
        for b in m.content:
            if isinstance(b, ImageBlock):
                has_images = True
            elif isinstance(b, FileRefBlock):
                has_files = True
    return has_images, has_files


@dataclass
class TurnPlan:
    """Plan for a single assistant turn.

    Held as a value object so the replay tool can inspect it without
    running the network call. Carries the BuiltContext alongside the
    wire payload so the replay tool can dump section-by-section
    token counts and RAG scores.
    """

    adapter: ProviderAdapter
    provider: str
    model: str
    messages: list[Message]  # post-compression, post-drift-note
    wire_request: dict[str, Any]
    truncated: bool
    dropped_count: int
    drift_detected: bool
    prompt_token_estimate: int
    context_window: int
    resolved_files: dict[str, ResolvedFile] = field(default_factory=dict)
    built_context: BuiltContext | None = None


async def plan_turn(
    history: list[Message],
    target_model: str,
    user_id: UUID | None = None,
    conversation_id: UUID | None = None,
) -> TurnPlan:
    """Assemble the request for `target_model` given canonical history.

    Steps (all provider-agnostic):
      1. Detect identity drift (prior assistant turn used a different
         model id).
      2. Load conversation-level artifacts (pinned, facts, summary).
      3. Run the six-part context engine to build the message list.
      4. Resolve files for THIS provider (vision vs description).
      5. Translate canonical messages to the provider wire format.
    """
    adapter = adapter_for(target_model)
    drift_detected = _detect_drift(history, target_model)

    pinned_context, extracted_facts, rolling_summary = await _load_conv_artifacts(
        conversation_id
    )

    user_message = history[-1] if history and history[-1].role == "user" else None

    built = await build_context(
        conversation_id=conversation_id,
        history=history,
        target_model=target_model,
        user_message=user_message,
        pinned_context=pinned_context,
        extracted_facts=extracted_facts,
        rolling_summary=rolling_summary,
        drift_detected=drift_detected,
        adapter=adapter,
    )

    messages = built.messages

    resolved_files = await resolve_files_for_turn(messages, adapter, user_id=user_id)

    # Phase 6 — adapter.translate_messages span. Attributes per the spec:
    # provider, message_count, has_images, has_files.
    has_images, has_files = _content_flags(messages)
    translate_span = _tracer.start_span("adapter.translate_messages")
    set_attributes(
        translate_span,
        provider=adapter.provider,
        message_count=len(messages),
        has_images=has_images,
        has_files=has_files,
    )
    try:
        wire_request = await adapter.translate_messages(messages, resolved_files)
    finally:
        try:
            translate_span.end()
        except Exception:
            pass

    # "Truncated" semantics carried over from Phase 2 for SSE consumers:
    # if compression ran (i.e. not passthrough), older turns are no
    # longer verbatim in the wire payload. Report them as "dropped" so
    # the UI can still surface a "Earlier messages summarized" banner.
    dropped = 0
    if not built.passthrough:
        from app.config import settings as _s
        from app.core.flags import flag as _flag

        # Mirror the context_engine.build_context window resolution so
        # the "dropped" count reported to the SSE client matches what
        # actually got compressed when compression_v2 is on.
        verbatim_n = 8 if _flag("compression_v2") else _s.verbatim_window_turns
        dropped = max(0, len(history) - verbatim_n)

    return TurnPlan(
        adapter=adapter,
        provider=adapter.provider,
        model=target_model,
        messages=messages,
        wire_request=wire_request,
        truncated=not built.passthrough,
        dropped_count=dropped,
        drift_detected=drift_detected,
        prompt_token_estimate=built.total_token_estimate,
        context_window=built.context_window,
        resolved_files=resolved_files,
        built_context=built,
    )


async def run_turn(plan: TurnPlan) -> AsyncIterator[StreamEvent]:
    """Execute the planned turn against the chosen provider.

    Yields canonical StreamEvents. Routers consume these and translate
    to SSE — that translation is the only place we touch HTTP shapes.
    """
    # Phase 6 — adapter.validate span.
    validate_span = _tracer.start_span("adapter.validate")
    set_attributes(validate_span, provider=plan.provider)
    validation = await plan.adapter.validate(plan.wire_request)
    set_attributes(
        validate_span,
        passed=validation.ok,
        failure_reason="; ".join(validation.errors) if validation.errors else None,
    )
    try:
        validate_span.end()
    except Exception:
        pass
    if not validation.ok:
        reason = "; ".join(validation.errors)
        log.warning(
            "context_engine.validation_failed",
            provider=plan.provider,
            reason=reason,
        )
        yield StreamEvent(
            type="error",
            content=f"validation_failed: {reason}",
        )
        return

    # Phase 6 — adapter.stream_completion span. We close it after the
    # final canonical event so latency_ms covers the full provider call.
    import time

    stream_span = _tracer.start_span("adapter.stream_completion")
    set_attributes(
        stream_span,
        provider=plan.provider,
        model=plan.model,
        was_fallback=False,  # set later by fallback wrapper if applicable
    )
    started = time.perf_counter()
    prompt_tokens = 0
    completion_tokens = 0
    try:
        async for event in await plan.adapter.stream_completion(plan.wire_request):
            if event.type == "stop" and isinstance(event.usage, dict):
                prompt_tokens = int(event.usage.get("prompt_tokens", 0) or 0)
                completion_tokens = int(event.usage.get("completion_tokens", 0) or 0)
            yield event
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        set_attributes(
            stream_span,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        try:
            stream_span.end()
        except Exception:
            pass


# ── Helpers ─────────────────────────────────────────────────────────────


def _detect_drift(history: list[Message], target_model: str) -> bool:
    """True when any prior assistant turn was generated by a different model."""
    for m in reversed(history):
        if m.role == "assistant" and m.model_used and m.model_used != target_model:
            return True
        if m.role == "assistant" and m.model_used == target_model:
            return False
    return False


async def _load_conv_artifacts(
    conversation_id: UUID | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """Pull pinned_context, extracted_facts, rolling_summary from the row.

    Returns empties when ``conversation_id`` is None (replay tool path
    where a synthetic history is being inspected, or test fixtures).
    """
    if conversation_id is None:
        return [], {}, None
    from app.orm import Conversation

    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return [], {}, None
        return (
            list(row.pinned_context or []),
            dict(row.extracted_facts or {}),
            row.rolling_summary,
        )


def provider_for_model(model: str) -> str:
    """Re-export of `adapters.provider_for` for orchestrator callers."""
    return provider_for(model)
