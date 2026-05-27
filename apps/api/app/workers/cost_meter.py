"""Cost meter Celery task — personal-use observability.

Triggered by the orchestrator after every assistant message persists.
Reads token_counts + model_used from the message row, computes cost
against a hard-coded price table, and writes one row to usage_events.

Idempotency: the usage_events table has UNIQUE on message_id. We use
``INSERT ... ON CONFLICT (message_id) DO NOTHING`` so a Celery retry on
the same message_id is a safe no-op.

Pricing context: the user is on FREE-TIER providers (Gemini AI Studio,
Groq, Mistral la Plateforme Experiment). Real out-of-pocket cost is $0.
The table below uses the public list price for each underlying model so
the dashboard shows "what this would cost on the paid tier" — a useful
"savings" signal, not a billing number. Tweak any row to change the
estimate without redeploying anything else.

Soft vs hard limit (Phase 5 personal-use ruleset):
  * ``DAILY_SOFT_LIMIT_USD`` — WARNING only. Sets a Redis flag so the
    dashboard can show a banner. Never blocks a request.
  * ``HARD_DAILY_LIMIT_USD`` (default unset) — the ONLY thing that ever
    blocks a request in personal mode. Checked by the orchestrator at
    turn entry. Documented here so the rule lives next to the code that
    enforces the soft limit.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import redis

from app.config import settings
from app.core.logging import get_logger
from app.workers.celery_app import celery_app
from app.workers.db_sync import sync_session

log = get_logger(__name__)
logger = log  # back-compat


def _current_span() -> Any:
    try:
        from opentelemetry import trace

        return trace.get_current_span()
    except Exception:
        return None


# ── Price table ─────────────────────────────────────────────────────────
# Per-token (NOT per-1k). Multiply token count directly.
# Values are list prices from the upstream provider, as of 2026-05.
# Free-tier users pay $0 — these are estimates for the dashboard.

PRICE_TABLE: dict[str, dict[str, float]] = {
    # ── Gemini (paid tier list prices; user is on free tier) ──────────
    "gemini-2.5-flash":      {"prompt": 0.00000030,   "completion": 0.0000025},
    "gemini-2.5-flash-lite": {"prompt": 0.000000075,  "completion": 0.0000003},
    "gemini-2.5-pro":        {"prompt": 0.00000125,   "completion": 0.000010},
    "gemini-2.0-flash":      {"prompt": 0.00000010,   "completion": 0.0000004},
    # ── Groq (free tier; numbers are Groq's published paid pricing) ──
    "groq-llama-3.1-8b":     {"prompt": 0.00000005,   "completion": 0.00000008},
    "groq-llama-3.3-70b":    {"prompt": 0.00000059,   "completion": 0.00000079},
    "groq-llama-vision":     {"prompt": 0.00000020,   "completion": 0.00000020},
    "groq-gemma2-9b":        {"prompt": 0.00000020,   "completion": 0.00000020},
    # ── Mistral la Plateforme (Experiment is free) ───────────────────
    "mistral-small-latest":  {"prompt": 0.00000020,   "completion": 0.00000060},
    "mistral-medium-latest": {"prompt": 0.000000275,  "completion": 0.00000081},
    "mistral-large-latest":  {"prompt": 0.000002,     "completion": 0.000006},
    "open-mistral-nemo":     {"prompt": 0.00000015,   "completion": 0.00000015},
}

# Fallback used when an unregistered model id slips through. Keeps the
# row from being NULL — the dashboard will still graph it.
_DEFAULT_PRICE = {"prompt": 0.0, "completion": 0.0}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Pure helper — also used by the replay tool's --show-cost flag."""
    p = PRICE_TABLE.get(model, _DEFAULT_PRICE)
    return prompt_tokens * p["prompt"] + completion_tokens * p["completion"]


# ── Token split heuristics ──────────────────────────────────────────────
# messages.token_counts is a JSONB map keyed by provider, holding a total.
# We don't currently split prompt vs completion at write time; the cost
# meter does it here by re-reading the conversation's prior tokens (the
# prompt) and inferring the completion as (total - prompt). When the
# provider's `usage` block ships separate counts in the future we'll
# read them directly.


def _redis_sync() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def _seconds_until_end_of_day(now: datetime) -> int:
    eod = datetime.combine(now.date(), dtime(23, 59, 59, tzinfo=timezone.utc))
    return max(int((eod - now).total_seconds()), 60)


@celery_app.task(name="app.workers.cost_meter.meter_usage", bind=True)
def meter_usage(
    self,  # noqa: ANN001 — celery bind=True self
    message_id: str,
    *,
    was_fallback: bool = False,
    fallback_reason: str | None = None,
    fallback_from: str | None = None,
    compression_used: bool = False,
    rag_chunks_retrieved: int | None = None,
    latency_ms: int | None = None,
) -> dict[str, float | int | str]:
    """Persist a usage_events row + update messages.cost_usd.

    Returns a summary dict for logging only — the task's effect is the
    DB write.
    """
    from sqlalchemy import select, text

    from app.adapters import provider_for
    from app.orm import Message

    msg_uuid = UUID(message_id)

    with sync_session() as s:
        row = s.execute(
            select(Message).where(Message.id == msg_uuid)
        ).scalar_one_or_none()
        if row is None:
            logger.warning("cost_meter: message %s not found", message_id)
            return {"status": "missing"}

        model = row.model_used or ""
        provider = provider_for(model) if model else "unknown"
        counts = dict(row.token_counts or {})
        total = int(counts.get(provider, 0) or 0)

        # Heuristic split: re-read the prior turns' cached counts under
        # the same provider to back out the prompt tokens for THIS turn.
        prompt_tokens = 0
        if row.conversation_id is not None:
            prior_total = s.execute(
                text(
                    """
                    SELECT COALESCE(SUM(
                        COALESCE((token_counts->>:p)::int, 0)
                    ), 0)
                    FROM messages
                    WHERE conversation_id = :cid
                      AND turn_index < :ti
                    """
                ),
                {"p": provider, "cid": row.conversation_id, "ti": row.turn_index},
            ).scalar_one()
            prompt_tokens = int(prior_total or 0)
        completion_tokens = max(total - prompt_tokens, 0) if total else 0

        cost = Decimal(
            str(round(estimate_cost_usd(model, prompt_tokens, completion_tokens), 6))
        )

        # Idempotent insert. ON CONFLICT (message_id) DO NOTHING means a
        # retry of meter_usage on the same message is a no-op.
        s.execute(
            text(
                """
                INSERT INTO usage_events (
                    conversation_id, message_id, model, provider,
                    prompt_tokens, completion_tokens, cost_usd,
                    was_fallback, fallback_reason, fallback_from,
                    compression_used, rag_chunks_retrieved, latency_ms
                ) VALUES (
                    :conversation_id, :message_id, :model, :provider,
                    :prompt_tokens, :completion_tokens, :cost_usd,
                    :was_fallback, :fallback_reason, :fallback_from,
                    :compression_used, :rag_chunks_retrieved, :latency_ms
                )
                ON CONFLICT (message_id) DO NOTHING
                """
            ),
            {
                "conversation_id": row.conversation_id,
                "message_id": msg_uuid,
                "model": model,
                "provider": provider,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost,
                "was_fallback": was_fallback,
                "fallback_reason": fallback_reason,
                "fallback_from": fallback_from,
                "compression_used": compression_used,
                "rag_chunks_retrieved": rag_chunks_retrieved,
                "latency_ms": latency_ms,
            },
        )
        row.cost_usd = cost
        s.commit()

    # Phase 6 — surface the cost in the worker's auto-instrumented span.
    span = _current_span()
    if span is not None:
        try:
            span.set_attribute("message_id", message_id)
            span.set_attribute("model", model or "unknown")
            span.set_attribute("cost_usd", float(cost))
        except Exception:
            pass

    _maybe_warn_soft_limit()

    return {
        "status": "ok",
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": float(cost),
        "was_fallback": int(was_fallback),
    }


def _maybe_warn_soft_limit() -> None:
    """Set daily_limit_warning=true in Redis if today's spend > soft limit.

    Soft warning ONLY. Never blocks a request. The dashboard polls this
    flag (or computes from usage_events) to render the warning banner.
    """
    try:
        from sqlalchemy import text

        with sync_session() as s:
            total = s.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events "
                    "WHERE ts >= NOW() - INTERVAL '1 day'"
                )
            ).scalar_one()
        total_f = float(total or 0)
        if total_f > settings.daily_soft_limit_usd:
            r = _redis_sync()
            now = datetime.now(timezone.utc)
            r.set(
                "daily_limit_warning",
                "true",
                ex=_seconds_until_end_of_day(now),
            )
            logger.warning(
                "cost_meter: daily soft limit exceeded total_usd=%.4f limit=%.4f",
                total_f,
                settings.daily_soft_limit_usd,
            )
    except Exception:
        logger.exception("cost_meter: soft-limit check failed")


def is_hard_limit_exceeded_sync() -> tuple[bool, float, float | None]:
    """Synchronous helper for the orchestrator pre-flight check.

    Returns (blocked, current_total_usd, limit). The orchestrator calls
    this BEFORE running the context engine so a blown hard limit fails
    fast without consuming compute.
    """
    limit = settings.hard_daily_limit_usd
    if limit is None:
        return False, 0.0, None
    try:
        from sqlalchemy import text

        with sync_session() as s:
            total = s.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events "
                    "WHERE ts >= NOW() - INTERVAL '1 day'"
                )
            ).scalar_one()
        total_f = float(total or 0)
        return total_f >= limit, total_f, limit
    except Exception:
        logger.exception("cost_meter: hard-limit check failed; allowing request")
        return False, 0.0, limit


def is_daily_warning_active_sync() -> bool:
    """Has the soft warning been raised today? Polled by /api/config/limits."""
    try:
        return _redis_sync().get("daily_limit_warning") == "true"
    except Exception:
        return False


# Trigger helper called by the conversations router.

def trigger_meter_usage(
    message_id: UUID,
    *,
    was_fallback: bool = False,
    fallback_reason: str | None = None,
    fallback_from: str | None = None,
    compression_used: bool = False,
    rag_chunks_retrieved: int | None = None,
    latency_ms: int | None = None,
) -> None:
    """Fire-and-forget queue call. Logs and swallows failures."""
    try:
        meter_usage.delay(
            str(message_id),
            was_fallback=was_fallback,
            fallback_reason=fallback_reason,
            fallback_from=fallback_from,
            compression_used=compression_used,
            rag_chunks_retrieved=rag_chunks_retrieved,
            latency_ms=latency_ms,
        )
    except Exception:
        logger.exception("cost_meter dispatch failed for %s — using fallback %s", message_id, today())


def today() -> date:
    return datetime.now(timezone.utc).date()
