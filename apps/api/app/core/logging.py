"""Structured JSON logging via structlog.

A single ``configure_logging()`` call wires structlog as the only sink,
replacing the noisy stdlib formatters. Every log line emerges as a
JSON object with at minimum:

  {timestamp, level, event, request_id, conversation_id?, trace_id?}

Sensitive fields are dropped on output. The drop list is conservative
(api_key, authorization, x_api_key, message_content, file_bytes,
embedding_vector) so a careless ``log.info(api_key=...)`` cannot leak
a secret — the field is removed before the JSON serializer sees it.

Per the Phase 6 hard constraint: "Structlog processors must never throw.
If a processor fails (e.g. the trace ID isn't available), it skips
gracefully." Every processor below is wrapped accordingly.

Context binding model:
  * ``contextvars`` carries the request_id (and optionally
    conversation_id) for the duration of a request via the middleware.
  * Workers / scripts can call ``bind_contextvars(conversation_id=...)``
    to add scoped context for their span of execution.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False


# Fields we never want to leak — drop before any renderer sees them.
# Names are checked case-insensitively. Don't add anything broad like
# "key" here — that would hide useful diagnostics (e.g. point_key).
_SENSITIVE_FIELDS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "x_api_key",
        "x-api-key",
        "message_content",
        "file_bytes",
        "embedding_vector",
        "gemini_api_key",
        "groq_api_key",
        "mistral_api_key",
    }
)


def _drop_sensitive(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets from the record. Never raises."""
    try:
        for key in list(event_dict.keys()):
            if key.lower() in _SENSITIVE_FIELDS:
                event_dict[key] = "<redacted>"
    except Exception:
        pass
    return event_dict


def _add_trace_id(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject the active OTel trace id when available. Never raises."""
    try:
        from app.core.tracing import current_trace_id_hex

        tid = current_trace_id_hex()
        if tid:
            event_dict.setdefault("trace_id", tid)
    except Exception:
        pass
    return event_dict


def _ensure_request_id(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Default the request_id field to '-' so every line has it.

    The middleware binds the real id via structlog's contextvars before
    the request runs; this processor exists as a safety net for code
    paths outside a request (Celery tasks, scripts, startup).
    """
    try:
        event_dict.setdefault("request_id", "-")
    except Exception:
        pass
    return event_dict


def _safe_processor_chain(processors: list[Any]) -> list[Any]:
    """Wrap each processor in a try/except so a buggy one never crashes the app.

    Stdlib logging behavior: a raise inside a processor surfaces as an
    unhandled exception in whatever code path emitted the log. We catch
    everything and pass the record through unchanged.
    """

    def _wrap(proc: Any) -> Any:
        def _wrapped(logger: Any, name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
            try:
                return proc(logger, name, event_dict)
            except Exception:
                # Swallow — structlog itself logs to stderr on processor
                # failure if we re-raise, which would loop.
                return event_dict

        return _wrapped

    return [_wrap(p) for p in processors]


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib bridge. Idempotent.

    Replaces the default stdlib handler so libraries that use
    ``logging.getLogger(__name__).info(...)`` also emit JSON.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _ensure_request_id,
        _add_trace_id,
        _drop_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=_safe_processor_chain(shared_processors)
        + [structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging through structlog so 3rd-party libs (litellm,
    # qdrant-client, sqlalchemy) also emit JSON lines via the same sink.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_safe_processor_chain(shared_processors),
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Silence the noisy auto-instrumented HTTP libs unless the user
    # explicitly turns the level back up via LOG_LEVEL.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Convenience re-export so callers don't import structlog directly."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


def bind_request_context(request_id: str, **fields: Any) -> None:
    """Bind a request_id + optional fields for the rest of this asyncio task.

    Used by the FastAPI middleware. Safe to call multiple times — later
    calls merge into the existing contextvars dict.
    """
    structlog.contextvars.bind_contextvars(request_id=request_id, **fields)


def clear_request_context() -> None:
    """Drop everything bound via ``bind_request_context``.

    The middleware calls this in a finally block so a request_id from one
    request can never leak into the next on the same worker thread.
    """
    structlog.contextvars.clear_contextvars()


def bind_contextvars(**fields: Any) -> None:
    """Re-export for non-request code paths (workers, scripts)."""
    structlog.contextvars.bind_contextvars(**fields)
