"""Redis-backed circuit breaker per provider.

State machine (ARCHITECTURE §"Circuit Breakers"):

    healthy    — no recent failures; route freely.
       │
       │  failure recorded; failure_count crosses threshold within window
       ▼
    degraded   — provider is skipped by the router until the degraded TTL
       │        expires. Failures stop being counted while degraded;
       │        all the bookkeeping has already happened.
       │
       │  degraded TTL elapses
       ▼
    half_open  — exactly one probe is allowed through. The next call's
                 outcome decides whether we go back to healthy (clear key)
                 or back to degraded (reset the TTL).

Data layout in Redis:

    circuit:<provider>           ZSET — failure timestamps (sliding window)
    circuit:<provider>:degraded  STRING (any value) — present == degraded
                                                      TTL == degraded_until

half_open is computed: the ZSET still exists past the window but no
degraded marker is present. That single-probe semantics is enforced
optimistically — we don't lock; if two probes race in half-open the
behavior degrades gracefully (one of them clears the key on success).

State lives in Redis only. If the API process restarts, breaker state
survives — this is a hard constraint from Phase 5.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)


CircuitState = Literal["healthy", "degraded", "half_open"]


@dataclass
class BreakerState:
    provider: str
    state: CircuitState
    failure_count: int
    degraded_until: float | None  # epoch seconds


_redis: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    """Use the CACHE Redis (db 0) — queue Redis is reserved for Celery."""
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _failures_key(provider: str) -> str:
    return f"circuit:{provider}"


def _degraded_key(provider: str) -> str:
    return f"circuit:{provider}:degraded"


def _log(transition: str, provider: str, **fields: Any) -> None:
    """Single log site for state transitions — invaluable in postmortems.

    Fields are emitted as a structured dict-ish suffix so a future log
    shipper (Phase 6) can json-parse them. Plain stdlib logging today.
    """
    payload = {"provider": provider, "transition": transition, **fields}
    logger.warning("circuit_breaker %s", json.dumps(payload, default=str))


async def record_failure(provider: str) -> BreakerState:
    """Record a failure timestamp; promote to degraded if the window fills.

    Idempotent in the sense that recording many failures past the threshold
    just re-asserts the degraded marker (resetting its TTL is intentional —
    keeps a flapping provider out longer).
    """
    r = _get_redis()
    now = time.time()
    fkey = _failures_key(provider)
    dkey = _degraded_key(provider)

    # Append failure timestamp, trim anything older than the window.
    cutoff = now - settings.circuit_window_seconds
    pipe = r.pipeline()
    pipe.zadd(fkey, {str(now): now})
    pipe.zremrangebyscore(fkey, 0, cutoff)
    pipe.zcard(fkey)
    pipe.expire(fkey, settings.circuit_window_seconds * 4)  # keep some history
    results = await pipe.execute()
    failure_count = int(results[2])

    if failure_count >= settings.circuit_failure_threshold:
        prior = await r.get(dkey)
        await r.set(dkey, "1", ex=settings.circuit_degraded_ttl_seconds)
        degraded_until = now + settings.circuit_degraded_ttl_seconds
        _log(
            "degraded" if prior is None else "degraded_extended",
            provider,
            failure_count=failure_count,
            degraded_until=degraded_until,
            window_seconds=settings.circuit_window_seconds,
        )
        return BreakerState(provider, "degraded", failure_count, degraded_until)

    return BreakerState(provider, "healthy", failure_count, None)


async def record_success(provider: str) -> BreakerState:
    """Successful call — clear the degraded marker AND failure window.

    Clearing the failure ZSET on success matches the spec's "health probes
    every 30 seconds reset breakers on success" behavior, generalized to
    any successful call. A single good call is a stronger signal than the
    half-open probe alone.
    """
    r = _get_redis()
    fkey = _failures_key(provider)
    dkey = _degraded_key(provider)

    prior_degraded = await r.exists(dkey)
    pipe = r.pipeline()
    pipe.delete(fkey)
    pipe.delete(dkey)
    await pipe.execute()

    if prior_degraded:
        _log("recovered", provider, failure_count=0)
    return BreakerState(provider, "healthy", 0, None)


async def is_available(provider: str) -> bool:
    """True when the router should TRY this provider.

    - healthy: True
    - degraded: False
    - half_open: True (one probe attempt allowed; caller is responsible
                       for recording the outcome)
    """
    state = await get_state(provider)
    return state.state in ("healthy", "half_open")


async def get_state(provider: str) -> BreakerState:
    """Read current breaker state without modifying it."""
    r = _get_redis()
    fkey = _failures_key(provider)
    dkey = _degraded_key(provider)

    pipe = r.pipeline()
    pipe.exists(dkey)
    pipe.pttl(dkey)
    pipe.zcard(fkey)
    pipe.zremrangebyscore(fkey, 0, time.time() - settings.circuit_window_seconds)
    pipe.zcard(fkey)
    results = await pipe.execute()
    degraded_present = bool(results[0])
    degraded_pttl_ms = int(results[1]) if results[1] and results[1] > 0 else 0
    fresh_count = int(results[4])

    if degraded_present:
        degraded_until = time.time() + (degraded_pttl_ms / 1000.0)
        return BreakerState(provider, "degraded", fresh_count, degraded_until)

    # No degraded marker. If there's still failure history hanging around
    # but it's stale (outside the window), we treat the provider as
    # half_open — one probe through, then full healthy on success.
    # We use raw zcard (NOT the windowed one) to decide: any history at
    # all post-degraded means we want one cautious probe.
    raw_history = await r.zcard(fkey)
    if raw_history > 0 and fresh_count == 0:
        return BreakerState(provider, "half_open", 0, None)
    return BreakerState(provider, "healthy", fresh_count, None)


async def get_all_states(providers: list[str] | None = None) -> dict[str, BreakerState]:
    """Snapshot every provider's breaker state.

    Used by both health probes (to schedule probes intelligently) and the
    dashboard (to render the live status panel).
    """
    if providers is None:
        # The router knows the canonical list — import here to dodge a
        # circular dep at module load.
        from app.router.provider_router import known_providers

        providers = known_providers()

    out: dict[str, BreakerState] = {}
    for p in providers:
        out[p] = await get_state(p)
    return out
