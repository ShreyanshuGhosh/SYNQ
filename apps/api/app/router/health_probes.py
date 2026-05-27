"""Periodic provider health probes.

Runs as a Celery Beat task on a fixed cadence. For each provider in the
fallback chain we issue a 1-token completion against the cheapest model
and record the result in two places:

  * Redis ``health:<provider>`` — last probe outcome for the dashboard.
  * Circuit breaker — failures push us toward degraded; successes clear.

Frequency note: the Phase 5 spec says 30 seconds. Free-tier providers
have daily request caps (Gemini ~1500/day, Groq has stricter), so we
bump this to 5 minutes via ``settings.health_probe_interval_seconds``.
At 5min cadence with 3 providers we use ~864 probe calls/day total,
comfortably under any single provider's free-tier ceiling.

We compute one probe per provider, not per model. A provider being up
implies any of its models can be tried.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import redis.asyncio as redis

from app.adapters import adapter_for
from app.config import settings
from app.models import Message, TextBlock
from app.router import circuit_breaker
from app.router.provider_router import _parse_chain
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


_PROBE_TEXT = "hi"


def _redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def _health_key(provider: str) -> str:
    return f"health:{provider}"


def _pick_probe_model(provider: str, chain: list[str]) -> str | None:
    """Pick the cheapest registered model for a given provider.

    Prefers an explicitly "cheap" model (flash/8b/etc) belonging to this
    provider; falls back to the first chain entry whose provider matches.
    """
    from app.router.provider_router import _is_cheap

    cheapest = None
    fallback = None
    for model in chain:
        try:
            if adapter_for(model).provider != provider:
                continue
        except Exception:  # noqa: BLE001
            continue
        if fallback is None:
            fallback = model
        if _is_cheap(model):
            cheapest = model
            break
    return cheapest or fallback


async def _probe_one(provider: str, model: str) -> dict[str, Any]:
    """Send a 1-token completion. Returns the dict we cache in Redis."""
    adapter = adapter_for(model)
    # Synthetic message — never persisted; only fed to translate_messages.
    # All DB-row fields are filled with throwaway values to satisfy the
    # Pydantic validator.
    msg = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        turn_index=0,
        role="user",
        content=[TextBlock(text=_PROBE_TEXT)],
        model_used=None,
        token_counts=None,
        cost_usd=None,
        embedding_status="done",
        idempotency_key=None,
        created_at=datetime.now(timezone.utc),
    )
    started = time.perf_counter()
    try:
        wire = await adapter.translate_messages([msg])
        # Most adapters accept a max_tokens / max_output_tokens hint; we
        # don't enforce it here because the cheap-model output is short
        # by nature and the provider's own minimum will apply. We only
        # care that the request round-trips.
        async for event in await adapter.stream_completion(wire):
            if event.type == "error":
                raise RuntimeError(str(event.content))
            if event.type == "stop":
                break
        latency_ms = int((time.perf_counter() - started) * 1000)
        await circuit_breaker.record_success(provider)
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "checked_at": time.time(),
            "model_used": model,
        }
    except Exception as exc:  # noqa: BLE001 — probe surfaces every error
        latency_ms = int((time.perf_counter() - started) * 1000)
        await circuit_breaker.record_failure(provider)
        return {
            "status": "unhealthy",
            "latency_ms": latency_ms,
            "checked_at": time.time(),
            "model_used": model,
            "error": str(exc)[:200],  # truncate — never log secrets
        }


async def _probe_all_async() -> dict[str, Any]:
    chain = _parse_chain()
    providers: list[str] = []
    seen: set[str] = set()
    for model in chain:
        try:
            p = adapter_for(model).provider
        except Exception:  # noqa: BLE001
            continue
        if p not in seen:
            seen.add(p)
            providers.append(p)

    r = _redis()
    results: dict[str, Any] = {}
    for provider in providers:
        model = _pick_probe_model(provider, chain)
        if model is None:
            continue
        result = await _probe_one(provider, model)
        results[provider] = result
        try:
            await r.set(
                _health_key(provider),
                json.dumps(result),
                ex=settings.health_state_ttl_seconds,
            )
        except Exception:
            logger.exception("health probe: redis write failed for %s", provider)
    return results


@celery_app.task(name="app.router.health_probes.probe_all_providers")
def probe_all_providers() -> dict[str, Any]:
    """Celery entrypoint. Runs the async probe sweep on the worker loop."""
    try:
        return asyncio.run(_probe_all_async())
    except RuntimeError:
        # If we're already inside an event loop (rare on celery solo
        # pool, but possible), fall back to a fresh loop.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_probe_all_async())
        finally:
            loop.close()


async def read_all_health() -> list[dict[str, Any]]:
    """Read every health:<provider> key and return as a list for the API.

    Missing/expired keys are returned with status='unknown' so the
    dashboard can render a grey dot rather than omit the row.
    """
    from app.router.provider_router import known_providers

    r = _redis()
    out: list[dict[str, Any]] = []
    for provider in known_providers():
        raw = await r.get(_health_key(provider))
        if raw is None:
            out.append(
                {
                    "provider": provider,
                    "status": "unknown",
                    "latency_ms": None,
                    "checked_at": None,
                    "model_used": None,
                }
            )
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        data["provider"] = provider
        # Mix in the breaker state so the UI can show half_open as amber.
        breaker_state = await circuit_breaker.get_state(provider)
        if breaker_state.state in ("degraded", "half_open"):
            data["status"] = breaker_state.state
        out.append(data)
    return out
