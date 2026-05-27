"""Phase 6 — personal-use observability primitives.

Three orthogonal pieces live here:

  * ``tracing``  — OpenTelemetry init + helper context managers used by
                   the hot path (context_engine, adapters) to add custom
                   spans without dragging the OTel SDK into every module.
  * ``logging``  — structlog configuration + FastAPI request_id middleware.
  * ``flags``    — env-var driven feature flags. No external service.

All three are written so the app survives if any of them is misconfigured:
exporters that can't reach Jaeger silently drop, logging processors that
raise are dropped per-record, and unknown flag names return False.
"""
