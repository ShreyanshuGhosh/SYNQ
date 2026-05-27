"""Worker dispatch helpers — fire-and-forget triggers from request path.

The conversations router calls these after persisting each turn. Failures
are logged but never raised — Celery being down must not break the live
chat path. Tasks are idempotent (see ``intelligence.py``), so missed
fires are recoverable by re-running the worker on the message id later.

The trigger policy for ``update_rolling_summary`` is decided HERE rather
than in the worker itself: orchestrators know the new turn count and
can compare to ``settings.summary_trigger_every_n_turns``. This keeps
the worker pure ("if you call me, I'll regenerate") and makes the
trigger decision a single readable expression at the call site.
"""

from __future__ import annotations

from uuid import UUID

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
logger = log  # back-compat


def trigger_embed_message(message_id: UUID) -> None:
    """Queue ``embed_message`` for a freshly-persisted message."""
    try:
        from app.workers.intelligence import embed_message

        embed_message.delay(str(message_id))
    except Exception:
        logger.exception("dispatch: embed_message queue failed for %s", message_id)


def trigger_extract_facts(conversation_id: UUID) -> None:
    """Queue ``extract_facts`` — runs after every turn per spec."""
    try:
        from app.workers.intelligence import extract_facts

        extract_facts.delay(str(conversation_id))
    except Exception:
        logger.exception(
            "dispatch: extract_facts queue failed for conv=%s", conversation_id
        )


def trigger_rolling_summary_if_due(
    conversation_id: UUID, total_turns: int, *, force: bool = False
) -> None:
    """Queue ``update_rolling_summary`` every N turns or on demand.

    ``force=True`` is used by the switch-model handler to refresh the
    summary if it's stale (spec: "every 10 new turns OR on switch event
    if stale"). The worker itself bails when already up-to-date, so the
    cheap-model call only happens when there's real work to do.
    """
    try:
        n = settings.summary_trigger_every_n_turns
        if not force and (n <= 0 or total_turns % n != 0):
            return
        from app.workers.intelligence import update_rolling_summary

        update_rolling_summary.delay(str(conversation_id))
    except Exception:
        logger.exception(
            "dispatch: update_rolling_summary queue failed for conv=%s",
            conversation_id,
        )
