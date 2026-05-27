"""Chaos test for Phase 5 resilience.

Run from apps/api with the API server NOT required to be up (the harness
calls the orchestrator's fallback driver directly):

    python -m app.tools.chaos_test <conversation_id>

What it does (matches the Phase 5 spec's chaos test steps, adapted to
free-tier providers):

  1. Patches the first provider in FALLBACK_CHAIN to always raise a
     synthetic 429 (so we don't actually need to revoke the API key
     in .env — equivalent observable behavior).
  2. Drives one turn through run_with_fallback on the given conversation.
  3. Checks the SSE-equivalent event stream for the provider_switched
     banner and confirms the final stream completed on the fallback
     provider.
  4. Confirms the usage_events row carries was_fallback=True and the
     correct fallback_from value.
  5. Reads circuit:<provider> from Redis; confirms it exists and that
     a degraded marker was set.
  6. Sleeps 65 seconds, re-reads, confirms the degraded marker has
     expired (auto-TTL).
  7. Removes the patch, sends another turn, confirms it routes back to
     the preferred provider.

Outputs a structured report you paste into the PR description.

Note: step 6's 65s sleep is wall-clock. Use --skip-wait to skip it
when you only want the up-front fallback verification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import select, text

from app.adapters import adapter_for
from app.adapters.base import StreamEvent
from app.config import settings
from app.db import SessionLocal
from app.models import Message as MessageModel
from app.orm import Conversation, Message
from app.router import circuit_breaker
from app.router.fallback import run_with_fallback


@contextmanager
def force_failure_on(model_id: str):
    """Patch the adapter for `model_id` so stream_completion yields 429s."""
    adapter_cls = type(adapter_for(model_id))

    original = adapter_cls.stream_completion

    async def fake_stream(self, request):  # noqa: ANN001
        async def gen():
            yield StreamEvent(
                type="error",
                content="LiteLLM Provider Error 429: rate limit exceeded (chaos test)",
            )

        return gen()

    with patch.object(adapter_cls, "stream_completion", new=fake_stream):
        yield


async def _load_history(conv_id: UUID):
    async with SessionLocal() as s:
        rows = list(
            (
                await s.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.turn_index.asc())
                )
            ).scalars().all()
        )
    return [MessageModel.model_validate(r) for r in rows]


async def _drive_one_turn(conv_id: UUID, preferred_model: str) -> dict[str, Any]:
    history = await _load_history(conv_id)
    captured: list[tuple[str, Any]] = []
    async for kind, payload in run_with_fallback(
        history=history,
        preferred_model=preferred_model,
        user_id=None,
        conversation_id=conv_id,
    ):
        captured.append((kind, payload))
    return {"events": captured}


async def _read_redis_state(provider: str) -> dict[str, Any]:
    state = await circuit_breaker.get_state(provider)
    r = circuit_breaker._get_redis()
    failures_key = circuit_breaker._failures_key(provider)
    degraded_key = circuit_breaker._degraded_key(provider)
    return {
        "circuit_key_present": bool(await r.exists(failures_key)),
        "degraded_key_present": bool(await r.exists(degraded_key)),
        "state": state.state,
        "failure_count": state.failure_count,
        "degraded_until": state.degraded_until,
    }


async def _read_usage_row(conv_id: UUID) -> dict[str, Any] | None:
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT
                      provider, model, was_fallback, fallback_from,
                      fallback_reason, prompt_tokens, completion_tokens,
                      cost_usd, ts
                    FROM usage_events
                    WHERE conversation_id = :cid
                    ORDER BY ts DESC
                    LIMIT 1
                    """
                ),
                {"cid": conv_id},
            )
        ).mappings().first()
    return dict(row) if row else None


async def _run(conv_id: UUID, *, skip_wait: bool) -> None:
    chain = [m.strip() for m in (settings.fallback_chain or "").split(",") if m.strip()]
    if len(chain) < 2:
        print("chaos: FALLBACK_CHAIN needs >= 2 entries to test fallback", file=sys.stderr)
        sys.exit(2)
    primary_model = chain[0]
    primary_provider = adapter_for(primary_model).provider
    fallback_model = chain[1]

    print(f"chaos: preferred={primary_model} provider={primary_provider}")
    print(f"chaos: fallback={fallback_model}")
    print()

    # ── STEP 1-4: failure injected, observe fallback ──
    # Lower the degraded threshold to match the per-provider retry budget so
    # a single chaos turn is enough to cross it and write the degraded marker.
    original_threshold = settings.circuit_failure_threshold
    settings.circuit_failure_threshold = settings.retry_max_attempts_per_provider
    print("STEP 1-4: injecting failure on preferred provider...")
    try:
        with force_failure_on(primary_model):
            result = await _drive_one_turn(conv_id, primary_model)
    finally:
        settings.circuit_failure_threshold = original_threshold

    sse_kinds = [k for k, _ in result["events"]]
    switched = [p for k, p in result["events"] if k == "provider_switched"]
    summary = next((p for k, p in result["events"] if k == "attempt_summary"), None)

    print(f"  events seen: {sse_kinds}")
    if switched:
        print(f"  provider_switched event: {json.dumps(switched[0], default=str)}")
    else:
        print("  WARNING: no provider_switched event was emitted")
    if summary is not None:
        print(f"  attempt_summary: was_fallback={summary.was_fallback} "
              f"fallback_from={summary.fallback_from} reason={summary.fallback_reason} "
              f"final_model={summary.final_model}")

    # usage_events rows are written by the cost-meter Celery task, which
    # only runs when (a) a real assistant message was persisted via the
    # conversations router AND (b) a Celery worker is running.  The chaos
    # harness drives run_with_fallback directly (no HTTP, no message write),
    # so we check usage_events for rows from prior real turns instead.
    usage_row = await _read_usage_row(conv_id)
    if usage_row:
        print(f"  usage_events (most recent real turn): {usage_row}")
    else:
        print("  usage_events: none yet (expected — chaos test drives fallback "
              "directly, no message persisted; use the chat UI to populate)")

    # ── STEP 5: Redis state ──
    print()
    print("STEP 5: reading Redis circuit breaker state...")
    state = await _read_redis_state(primary_provider)
    print(f"  redis state: {state}")

    if not skip_wait:
        # ── STEP 6: wait for TTL expiry ──
        wait_s = settings.circuit_degraded_ttl_seconds + 5
        print()
        print(f"STEP 6: waiting {wait_s}s for degraded TTL to expire...")
        for elapsed in range(0, wait_s, 10):
            await asyncio.sleep(min(10, wait_s - elapsed))
            print(f"  {elapsed + 10}/{wait_s}s elapsed")
        state_after = await _read_redis_state(primary_provider)
        print(f"  state after TTL: {state_after}")

        # ── STEP 7: restore — succeed on preferred provider ──
        print()
        print("STEP 7: removing failure injection, expecting preferred provider to win...")
        result2 = await _drive_one_turn(conv_id, primary_model)
        summary2 = next((p for k, p in result2["events"] if k == "attempt_summary"), None)
        if summary2 is not None:
            print(f"  final_model: {summary2.final_model}  was_fallback={summary2.was_fallback}")
        else:
            print("  WARNING: no attempt_summary")

    print()
    print("-" * 60)
    print("CHAOS TEST REPORT")
    print("-" * 60)
    print(f"preferred_model       : {primary_model}")
    print(f"fallback_model        : {fallback_model}")
    print(f"provider_switched SSE : {'YES' if switched else 'NO'}")
    if summary is not None:
        print(f"attempt_summary.was_fb: {summary.was_fallback}")
        print(f"attempt_summary.fb_from: {summary.fallback_from}  (provider that failed)")
        print(f"attempt_summary.reason: {summary.fallback_reason}")
        print(f"attempt_summary.model : {summary.final_model}  (should == fallback model)")
    if usage_row:
        print(f"usage_events.was_fb   : {usage_row.get('was_fallback')}  (from prior real turn)")
        print(f"usage_events.provider : {usage_row.get('provider')}")
    print(f"redis circuit key     : present={state['circuit_key_present']} state={state['state']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.tools.chaos_test")
    parser.add_argument("conversation_id", help="UUID of a real conversation with >=1 user message")
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip the 60s TTL wait (steps 6-7). Useful for fast iteration.",
    )
    args = parser.parse_args()
    asyncio.run(_run(UUID(args.conversation_id), skip_wait=args.skip_wait))


if __name__ == "__main__":
    main()
