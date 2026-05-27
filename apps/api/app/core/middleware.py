"""Cross-cutting FastAPI middleware for Phase 6.

Currently one middleware: ``RequestContextMiddleware`` generates a UUID
per request and binds it to the structlog contextvars so every log line
fired during that request carries ``request_id=...``.

The request_id is also echoed in the response header ``X-Request-Id`` so
callers (browser, curl, the dashboard panel) can quote it back when
reporting an issue.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_context, clear_request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a unique request_id for the duration of each HTTP request."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        # Honor an inbound X-Request-Id if the caller supplied one — makes
        # it trivial to correlate browser logs with API logs without
        # needing the trace UI open.
        inbound = request.headers.get("X-Request-Id") or request.headers.get("x-request-id")
        request_id = inbound or uuid4().hex
        bind_request_context(request_id=request_id)
        try:
            response: Response = await call_next(request)
        finally:
            clear_request_context()
        response.headers.setdefault("X-Request-Id", request_id)
        return response
