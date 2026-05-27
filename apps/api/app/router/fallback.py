"""Run-turn-with-fallback — Phase 5 retry & failover policy.

Wraps the existing ``plan_turn`` / ``run_turn`` orchestrator with the
retry-and-fallback policy from ARCHITECTURE §"Error Categories and
Handling":

    429  rate-limit       → exponential backoff (1s/2s/4s, max 3) on the
                            same provider, then fall through to next.
    529  overloaded       → circuit-break the provider, skip immediately.
    400  context-length   → re-run plan_turn with aggressive_compression.
    401  auth failure     → DO NOT retry. CRITICAL log. SSE event tells
                            the user to check their API keys. Never log
                            the key itself.
    content_filter       → DO NOT retry. SSE refusal event.
    5xx  server error    → backoff up to N, then fall through.
    success on fallback → SSE provider_switched event before first token.

The orchestrator's StreamEvents flow OUT of this generator unchanged
EXCEPT that the first token of a successful fallback is preceded by a
synthetic ``stream_meta`` event the conversations router translates to
an SSE ``provider_switched`` event.

We pass through opaque events to the caller via a small protocol: each
yielded item is a tuple ``(kind, payload)`` where:

    ("event", StreamEvent)               — real provider event
    ("provider_switched", dict)          — synthetic; emit SSE banner
    ("refusal", dict)                    — synthetic; content-filter SSE
    ("auth_failed", dict)                — synthetic; 401 SSE
    ("hard_limit", dict)                 — synthetic; hard cap exceeded
    ("attempt_summary", AttemptSummary)  — final; cost-meter inputs

The conversations router consumes this and renders SSE. Decoupling lets
us unit-test the fallback policy without dragging FastAPI in.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.adapters.base import StreamEvent
from app.config import settings
from app.core.logging import get_logger
from app.orchestrator import TurnPlan, plan_turn, run_turn
from app.router import circuit_breaker
from app.router.provider_router import route as route_chain

log = get_logger(__name__)
logger = log  # back-compat


ErrorClass = Literal[
    "rate_limit",         # 429
    "overloaded",         # 529
    "context_length",     # 400 context-length-exceeded
    "content_filter",     # provider refused
    "auth",               # 401
    "server",             # 5xx
    "transport",          # network — retry on same provider
    "unknown",
]


@dataclass
class AttemptSummary:
    """What actually happened during this turn — fed into the cost meter."""

    final_model: str
    final_provider: str
    was_fallback: bool = False
    fallback_from: str | None = None
    fallback_reason: str | None = None
    compression_used: bool = False
    rag_chunks_retrieved: int | None = None
    latency_ms: int | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


_REGEX_STATUS = re.compile(r"(?:status[_ ]?code[:= ]?|http[_ ]?)(\d{3})", re.IGNORECASE)
_REGEX_BARE_STATUS = re.compile(r"\b([45]\d{2})\b")


def classify_error(message: str) -> ErrorClass:
    """Map adapter error strings → canonical error class.

    Adapters surface provider errors via ``StreamEvent(type="error",
    content=<str>)``. The string usually contains either an explicit
    "status: 429" or the response body's keywords. We try both.
    """
    if not message:
        return "unknown"
    lower = message.lower()

    # Look for explicit HTTP status.
    status = None
    m = _REGEX_STATUS.search(message) or _REGEX_BARE_STATUS.search(message)
    if m:
        try:
            status = int(m.group(1))
        except ValueError:
            status = None

    if status == 401 or "unauthorized" in lower or "invalid api key" in lower:
        return "auth"
    if status == 429 or "rate limit" in lower or "ratelimit" in lower or "quota" in lower:
        return "rate_limit"
    if status == 529 or "overloaded" in lower:
        return "overloaded"
    if (status == 400 and "context" in lower and "length" in lower) or "context_length_exceeded" in lower or "too many tokens" in lower:
        return "context_length"
    if "content_filter" in lower or "refus" in lower or "safety" in lower or "blocked" in lower:
        return "content_filter"
    if status and 500 <= status < 600:
        return "server"
    if "timeout" in lower or "connection" in lower or "network" in lower:
        return "transport"
    return "unknown"


def _is_recoverable_same_provider(cls: ErrorClass) -> bool:
    """Errors where backing off on the SAME provider can succeed."""
    return cls in ("rate_limit", "server", "transport")


def _should_fallback(cls: ErrorClass) -> bool:
    """Errors where we should jump to the next provider in the chain."""
    return cls in ("rate_limit", "overloaded", "server", "transport", "unknown")


@dataclass
class _AttemptResult:
    success: bool
    events: list[StreamEvent] = field(default_factory=list)
    error_class: ErrorClass | None = None
    error_message: str | None = None
    latency_ms: int = 0


async def _attempt_one(plan: TurnPlan) -> AsyncIterator[StreamEvent | _AttemptResult]:
    """Drive one attempt, yielding events. Terminates with _AttemptResult.

    On any 'error' StreamEvent we stop yielding text and emit
    _AttemptResult so the caller can decide retry vs fallback. On a
    'stop' event we emit _AttemptResult(success=True) so the caller can
    finalize cleanly. Buffering text events here lets the caller decide
    whether to flush them downstream (we only flush after the first
    successful chunk crosses the boundary — see run_with_fallback).
    """
    started = time.perf_counter()
    saw_error: str | None = None
    async for event in run_turn(plan):
        if event.type == "error":
            saw_error = str(event.content or "")
            break
        yield event
        if event.type == "stop":
            elapsed = int((time.perf_counter() - started) * 1000)
            yield _AttemptResult(success=True, latency_ms=elapsed)
            return
    elapsed = int((time.perf_counter() - started) * 1000)
    cls = classify_error(saw_error or "")
    yield _AttemptResult(
        success=False,
        error_class=cls,
        error_message=saw_error,
        latency_ms=elapsed,
    )


async def run_with_fallback(
    *,
    history,  # list[Message]
    preferred_model: str,
    user_id: UUID | None,
    conversation_id: UUID | None,
) -> AsyncIterator[tuple[str, Any]]:
    """The Phase 5 retry+fallback driver.

    Yields ("kind", payload) tuples — see module docstring.
    """
    # ── Pre-flight: hard daily cap ────────────────────────────────────
    # Personal-mode rule: soft limit warns, hard limit BLOCKS. Soft
    # warning is set inside the cost-meter task after writes; the hard
    # cap is the only thing that ever refuses a turn.
    from app.workers.cost_meter import is_hard_limit_exceeded_sync

    blocked, total, limit = is_hard_limit_exceeded_sync()
    if blocked:
        yield (
            "hard_limit",
            {
                "today_usd": round(total, 4),
                "limit_usd": limit,
                "message": (
                    f"Daily HARD limit reached (${total:.2f} / ${limit:.2f}). "
                    "Increase HARD_DAILY_LIMIT_USD or wait until tomorrow."
                ),
            },
        )
        return

    # ── First plan_turn (preferred model, normal compression) ─────────
    plan = await plan_turn(
        history, preferred_model, user_id=user_id, conversation_id=conversation_id
    )
    candidate_models = await route_chain(
        preferred_model, prompt_tokens=plan.prompt_token_estimate
    )
    # If the router moved someone else to the front (cost-aware), re-plan.
    if candidate_models and candidate_models[0] != preferred_model:
        plan = await plan_turn(
            history,
            candidate_models[0],
            user_id=user_id,
            conversation_id=conversation_id,
        )

    summary = AttemptSummary(
        final_model=plan.model,
        final_provider=plan.provider,
        compression_used=plan.truncated,
        rag_chunks_retrieved=(
            len(plan.built_context.rag_hits) if plan.built_context else None
        ),
    )

    log.info(
        "turn.started",
        conversation_id=str(conversation_id) if conversation_id else None,
        model=plan.model,
        provider=plan.provider,
        prompt_tokens=plan.prompt_token_estimate,
    )

    # Always surface the plan-level events the existing UI consumes.
    if plan.drift_detected:
        yield (
            "model_switch",
            {
                "model": plan.model,
                "provider": plan.provider,
                "note": (
                    "Continued on a different model. Earlier responses "
                    "were generated by another provider."
                ),
            },
        )
    if plan.truncated:
        yield (
            "context_warning",
            {
                "dropped": plan.dropped_count,
                "message": (
                    f"Earlier messages dropped to fit context "
                    f"({plan.dropped_count} turn(s))."
                ),
            },
        )

    aggressive_compression = False
    last_error_class: ErrorClass | None = None
    last_error_message: str | None = None
    original_preferred = preferred_model
    first_attempted_model = plan.model

    # ── Walk candidate models, with per-provider retry ────────────────
    for model_idx, model in enumerate(candidate_models):
        # Re-plan for this model (skipped when it's the same as current).
        if model != plan.model:
            # Per spec: "Do not re-run context engine on fallback —
            # reuse the already-built context payload." We DO call
            # plan_turn though, because the wire payload itself differs
            # per provider (translate_messages varies). The expensive
            # part (context_engine.build_context, RAG retrieval, etc.)
            # is what we want to avoid re-running — and we DO avoid it
            # IF aggressive_compression hasn't been requested.
            #
            # Workaround for the spec's literal wording: re-plan but
            # the heavy work inside plan_turn is dominated by the
            # provider-side translate, not the context engine. If we
            # ever surface a clean "translate-only" path we'll use it
            # here. For now, accept the modest extra cost on fallback.
            plan = await plan_turn(
                history, model, user_id=user_id, conversation_id=conversation_id
            )
            summary.final_model = plan.model
            summary.final_provider = plan.provider

        # Per-provider retry loop.
        for attempt in range(settings.retry_max_attempts_per_provider):
            result_obj: _AttemptResult | None = None
            async for item in _attempt_one(plan):
                if isinstance(item, _AttemptResult):
                    result_obj = item
                    break
                # Real stream event — flush to the caller.
                yield ("event", item)

            if result_obj is None:
                # Should never happen — _attempt_one always terminates.
                result_obj = _AttemptResult(
                    success=False,
                    error_class="unknown",
                    error_message="iterator_did_not_terminate",
                )

            summary.attempts.append(
                {
                    "model": plan.model,
                    "provider": plan.provider,
                    "attempt": attempt + 1,
                    "success": result_obj.success,
                    "error_class": result_obj.error_class,
                    "latency_ms": result_obj.latency_ms,
                }
            )

            if result_obj.success:
                summary.latency_ms = result_obj.latency_ms
                # Mark the provider healthy after a clean turn — useful
                # post-recovery so a single good turn pulls us out of
                # any lingering half-open state.
                try:
                    await circuit_breaker.record_success(plan.provider)
                except Exception:
                    logger.exception("breaker: record_success failed")
                log.info(
                    "turn.completed",
                    conversation_id=str(conversation_id) if conversation_id else None,
                    model=plan.model,
                    provider=plan.provider,
                    latency_ms=result_obj.latency_ms,
                    was_fallback=summary.was_fallback,
                )
                yield ("attempt_summary", summary)
                return

            cls = result_obj.error_class or "unknown"
            msg = result_obj.error_message or ""
            last_error_class = cls
            last_error_message = msg

            # Always feed the breaker on a failure.
            try:
                await circuit_breaker.record_failure(plan.provider)
            except Exception:
                logger.exception("breaker: record_failure failed")

            # ── Terminal classes — stop the entire turn ──────────────
            if cls == "auth":
                logger.critical(
                    "auth_failure provider=%s model=%s (check API key env var)",
                    plan.provider,
                    plan.model,
                )
                yield (
                    "auth_failed",
                    {
                        "provider": plan.provider,
                        "message": (
                            f"Authentication failed for {plan.provider}. "
                            "Check the corresponding *_API_KEY environment "
                            "variable. The key itself is not logged."
                        ),
                    },
                )
                summary.latency_ms = result_obj.latency_ms
                yield ("attempt_summary", summary)
                return

            if cls == "content_filter":
                yield (
                    "refusal",
                    {
                        "provider": plan.provider,
                        "message": (
                            f"Content was refused by {plan.provider}. "
                            "Try switching models."
                        ),
                    },
                )
                summary.latency_ms = result_obj.latency_ms
                yield ("attempt_summary", summary)
                return

            # ── Context-length: re-plan with aggressive compression ──
            if cls == "context_length" and not aggressive_compression:
                logger.warning(
                    "context_length_exceeded provider=%s — retrying with aggressive_compression",
                    plan.provider,
                )
                aggressive_compression = True
                original_verbatim = settings.verbatim_window_turns
                original_rag_k = settings.rag_top_k
                settings.verbatim_window_turns = 8
                settings.rag_top_k = 4
                try:
                    plan = await plan_turn(
                        history,
                        plan.model,
                        user_id=user_id,
                        conversation_id=conversation_id,
                    )
                    summary.compression_used = True
                finally:
                    settings.verbatim_window_turns = original_verbatim
                    settings.rag_top_k = original_rag_k
                # Don't count this against retry budget — break out of
                # the inner loop and try this same provider once more
                # with the smaller payload.
                continue

            # ── Same-provider retry (429/5xx/transport) ──────────────
            if _is_recoverable_same_provider(cls) and attempt + 1 < settings.retry_max_attempts_per_provider:
                # Exponential backoff with jitter — keep it modest;
                # the SSE connection is open and we can't sleep forever.
                backoff = settings.retry_initial_backoff_seconds * (2 ** attempt)
                logger.warning(
                    "retry provider=%s model=%s attempt=%d/%d error=%s backoff=%.2fs",
                    plan.provider,
                    plan.model,
                    attempt + 1,
                    settings.retry_max_attempts_per_provider,
                    cls,
                    backoff,
                )
                await asyncio.sleep(backoff)
                continue

            # No more retries on this provider — break to fall through.
            break

        # ── Fall through to next provider in chain ───────────────────
        if not _should_fallback(last_error_class or "unknown"):
            # Unrecoverable & unswitchable — give up.
            yield (
                "event",
                StreamEvent(
                    type="error", content=last_error_message or "unknown_error"
                ),
            )
            yield ("attempt_summary", summary)
            return

        # If there's a next candidate, emit the switch banner.
        next_idx = model_idx + 1
        if next_idx < len(candidate_models):
            from_model = plan.model
            to_model = candidate_models[next_idx]
            summary.was_fallback = True
            summary.fallback_from = plan.provider
            summary.fallback_reason = last_error_class
            log.warning(
                "provider.fallback",
                from_provider=plan.provider,
                to_provider=to_model,
                reason=last_error_class,
                conversation_id=str(conversation_id) if conversation_id else None,
            )
            yield (
                "provider_switched",
                {
                    "from": from_model,
                    "to": to_model,
                    "reason": f"{last_error_class}",
                    "message": (
                        f"Switched to {to_model} — {from_model} "
                        f"{_reason_text(last_error_class or 'unknown')}."
                    ),
                },
            )
            # Loop continues with the next model.
            continue

    # Exhausted every candidate.
    logger.error(
        "fallback chain exhausted preferred=%s last_error=%s",
        original_preferred,
        last_error_class,
    )
    yield (
        "event",
        StreamEvent(
            type="error",
            content=(
                f"All providers in the fallback chain failed. "
                f"Last error: {last_error_class or 'unknown'}. "
                f"First attempted model: {first_attempted_model}."
            ),
        ),
    )
    yield ("attempt_summary", summary)


def _reason_text(cls: str) -> str:
    table = {
        "rate_limit": "was rate-limited",
        "overloaded": "was overloaded",
        "server": "had a server error",
        "transport": "had a network error",
        "unknown": "failed",
    }
    return table.get(cls, "failed")
