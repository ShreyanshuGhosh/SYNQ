"""Thin compatibility surface for Phase 1 callers.

Phase 2 moved the real LLM work into `app.adapters` and `app.orchestrator`.
This module is kept as a tiny re-export layer so any imports that still
say `from app.llm import ...` keep working until the codebase is fully
migrated. Nothing here contains provider-specific code.
"""

from __future__ import annotations

from app.adapters import StreamEvent, provider_for


def token_counts_from_usage(
    model: str, usage: dict[str, int] | None
) -> dict[str, int] | None:
    """Build the messages.token_counts JSONB map keyed by provider id."""
    if usage is None:
        return None
    return {provider_for(model): usage.get("total_tokens") or 0}


__all__ = ["StreamEvent", "token_counts_from_usage"]
