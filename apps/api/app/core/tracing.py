"""OpenTelemetry tracing — personal-use observability.

A single ``configure_tracing()`` call at FastAPI startup sets up:

  * The global tracer provider with our service name.
  * Auto-instrumentation for FastAPI and SQLAlchemy.
  * OTLP gRPC exporter pointed at Jaeger (default localhost:4317).

Custom spans are added in the hot path using ``tracer = get_tracer()``
and ``with tracer.start_as_current_span("name") as span: span.set_attribute(...)``.

Hard constraint: if Jaeger is unreachable, the app must continue working.
We use a BatchSpanProcessor with a dropping behavior on exporter failure,
and wrap the configure call itself in try/except so a missing OTLP endpoint
never crashes the API.

Auto-instrumentation for Celery happens inside the worker process — see
``workers/celery_app.py`` for the equivalent setup on that side.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# Public flag — modules that add custom spans check this before doing work
# that would otherwise be wasted (e.g. computing attribute values).
_TRACING_ENABLED = False


def configure_tracing(service_name: str | None = None) -> bool:
    """Initialize OTel SDK + exporter. Idempotent (safe to call twice).

    Returns True when tracing is live, False when it could not be set up
    for any reason. Callers should treat the return value as advisory only;
    ``get_tracer()`` always returns a working tracer (a no-op one when
    tracing is disabled).
    """
    global _TRACING_ENABLED
    if _TRACING_ENABLED:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        logger.info(
            "tracing: opentelemetry SDK not installed; tracing disabled"
        )
        return False

    try:
        name = (
            service_name
            or os.environ.get("OTEL_SERVICE_NAME")
            or "context-switcher-api"
        )
        endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )

        resource = Resource.create({"service.name": name})
        provider = TracerProvider(resource=resource)

        # `insecure=True` matches the Jaeger all-in-one default which
        # accepts plain gRPC on 4317. The OTLP exporter swallows network
        # errors internally — failed exports do not raise.
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _instrument_libraries()

        _TRACING_ENABLED = True
        logger.info(
            "tracing: configured service=%s endpoint=%s", name, endpoint
        )
        return True
    except Exception:
        # Per the Phase 6 spec: "zero-impact on the hot path; if Jaeger is
        # down or unreachable, the app continues working normally."
        logger.exception("tracing: configure failed; continuing without tracing")
        return False


def _instrument_libraries() -> None:
    """Auto-instrument the libraries we care about. Each is best-effort."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # FastAPIInstrumentor.instrument() patches the framework globally.
        # The router-level instrumentor wraps a specific app instance
        # later (see main.py) — we still call this to enable the default
        # context propagation hooks.
        FastAPIInstrumentor().instrument()
    except Exception:
        logger.info("tracing: fastapi auto-instrument unavailable")

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
    except Exception:
        logger.info("tracing: sqlalchemy auto-instrument unavailable")


def configure_celery_tracing() -> bool:
    """Worker-side equivalent of ``configure_tracing()``.

    Called from ``app.workers.celery_app`` so each worker gets its own
    tracer provider + the Celery auto-instrumentation hook that produces
    one span per task automatically.
    """
    if not configure_tracing():
        return False
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
        return True
    except Exception:
        logger.info("tracing: celery auto-instrument unavailable")
        return False


def get_tracer(name: str = "synq"):  # type: ignore[no-untyped-def]
    """Return a tracer. Safe to call when tracing is disabled (no-op tracer)."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


def set_attributes(span: Any, **attrs: Any) -> None:
    """Set multiple attributes on a span at once, tolerantly.

    Skip None values, coerce booleans / numbers / strings as-is, and
    str() everything else. Never raises — used in the hot path.
    """
    if span is None:
        return
    try:
        for k, v in attrs.items():
            if v is None:
                continue
            if isinstance(v, (bool, int, float, str)):
                span.set_attribute(k, v)
            elif isinstance(v, (list, tuple)):
                # OTel attributes can be sequences of primitives — coerce
                # to strings for safety on heterogeneous lists.
                try:
                    span.set_attribute(k, [str(x) for x in v])
                except Exception:
                    span.set_attribute(k, str(v))
            else:
                span.set_attribute(k, str(v))
    except Exception:
        pass


def current_trace_id_hex() -> str | None:
    """Return the current span's trace id as hex (16 bytes -> 32 chars), or None.

    Used by the structlog processor to inject ``trace_id`` into every log
    line that fires inside an active span. Returns None when there is no
    active span — never raises.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is None or not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:
        return None


class _NoopSpan:
    """Returned when tracing is fully disabled. Mimics the SDK Span API."""

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add_event(self, *args: Any, **kwargs: Any) -> None:
        return None

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *args: Any, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()

    def start_span(self, *args: Any, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()
