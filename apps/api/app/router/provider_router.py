"""Provider router — fallback-chain assembly.

Hard constraint from the Phase 5 spec: this module ASKS the breaker
whether a provider is available; it does NOT implement breaker logic
itself. Routing and circuit-breaking are decoupled.

Inputs:
  * Comma-separated FALLBACK_CHAIN env var (canonical model ids).
  * The user's preferred model for this turn.
  * Prompt token estimate (for cost-aware shortcut).

Output:
  * Ordered list of candidate model ids the orchestrator should try in
    sequence. Breaker-degraded models are filtered out unless they're
    the only option (we always return at least one candidate so the
    caller doesn't have to special-case empty).
"""

from __future__ import annotations

import logging

from app.adapters import adapter_for, list_models
from app.config import settings
from app.router import circuit_breaker

logger = logging.getLogger(__name__)


# Models considered "cheap" for the cost-aware promotion shortcut.
# Free-tier substitutes for the spec's "Haiku/gpt-4o-mini" tier.
# Match by substring so future-added variants (e.g. "gemini-2.5-flash-lite")
# automatically qualify.
_CHEAP_MODEL_SUBSTRINGS = ("flash", "haiku", "mini", "lite", "small", "8b", "9b")


def _parse_chain() -> list[str]:
    raw = (settings.fallback_chain or "").strip()
    if not raw:
        return []
    return [m.strip() for m in raw.split(",") if m.strip()]


def known_providers() -> list[str]:
    """Distinct provider ids reachable through the fallback chain.

    Used by the circuit breaker to enumerate state and by the health
    probe scheduler.
    """
    seen: dict[str, None] = {}
    for model in _parse_chain():
        try:
            seen.setdefault(adapter_for(model).provider, None)
        except Exception:  # noqa: BLE001 — registry lookups must not crash routing
            continue
    return list(seen.keys())


def get_chain() -> list[dict[str, str]]:
    """Public chain view for the dashboard: [{model, provider}, ...]."""
    out: list[dict[str, str]] = []
    for model in _parse_chain():
        try:
            out.append({"model": model, "provider": adapter_for(model).provider})
        except Exception:  # noqa: BLE001
            out.append({"model": model, "provider": "unknown"})
    return out


def _is_cheap(model: str) -> bool:
    lower = model.lower()
    return any(tag in lower for tag in _CHEAP_MODEL_SUBSTRINGS)


def _position_aware_chain(preferred_model: str, chain: list[str]) -> list[str]:
    """If preferred_model is in the chain, start from its position.

    Otherwise the preferred model goes at the front and the full chain
    follows (de-duped). This handles the case where the user picked a
    model that isn't in the fallback chain but we still want to try it
    first.
    """
    if preferred_model in chain:
        idx = chain.index(preferred_model)
        ordered = chain[idx:] + chain[:idx]
        # Don't loop back through earlier-in-chain models — they were
        # explicitly demoted by the user's choice.
        return chain[idx:]
    # Unknown / off-chain preferred model: try it first, then the whole chain.
    return [preferred_model, *[m for m in chain if m != preferred_model]]


async def route(
    preferred_model: str,
    *,
    prompt_tokens: int | None = None,
) -> list[str]:
    """Return the ordered list of candidate models for this turn.

    Steps:
      1. Position-aware: walk the chain starting at `preferred_model`.
      2. Cost-aware: if the prompt is small AND a cheap model is in the
         chain AND cost-aware routing is on, promote the cheap model to
         the head. Only one promotion — we don't reorder multiple times.
      3. Filter out breaker-degraded providers. Keep the original order
         for survivors. If everything is degraded, fall back to the full
         ordered list (the alternative is "user gets a 503 because every
         provider had a hiccup" — bad UX, better to try anyway).

    The orchestrator iterates this list and calls each model in turn,
    falling through on 429/529/breaker-open per the Phase 5 retry policy.
    """
    chain = _parse_chain()
    if not chain:
        # No fallback configured — return just the user's choice.
        return [preferred_model]

    ordered = _position_aware_chain(preferred_model, chain)

    if (
        settings.cost_aware_routing
        and prompt_tokens is not None
        and prompt_tokens < settings.cost_aware_prompt_threshold
    ):
        cheap = next((m for m in ordered if _is_cheap(m)), None)
        if cheap is not None and ordered[0] != cheap:
            ordered = [cheap, *[m for m in ordered if m != cheap]]
            logger.info(
                "router: cost-aware shortcut promoted %s (prompt_tokens=%d)",
                cheap,
                prompt_tokens,
            )

    # Filter against the circuit breaker. We resolve providers lazily so
    # an adapter lookup failure (unknown model id) doesn't take the whole
    # route() down — just drop that one candidate.
    available: list[str] = []
    skipped: list[str] = []
    for model in ordered:
        try:
            provider = adapter_for(model).provider
        except Exception:  # noqa: BLE001
            skipped.append(model)
            continue
        if await circuit_breaker.is_available(provider):
            available.append(model)
        else:
            skipped.append(model)

    if skipped:
        logger.info("router: skipping degraded providers via models=%s", skipped)

    if available:
        return available

    # Everything degraded — return the full ordered chain so the caller
    # at least attempts a request. The breaker will record the failure
    # and the user sees an error message rather than silent black-hole.
    logger.warning("router: all providers degraded; attempting full chain anyway")
    return ordered


def known_models() -> list[str]:
    """All canonical model ids — chain + registry. Used by the dashboard."""
    chain_models = set(_parse_chain())
    registry_models = {m["id"] for m in list_models()}
    return sorted(chain_models | registry_models)
