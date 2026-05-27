from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.tracing import configure_tracing
from app.routers import conversations, dashboard, files, flags, webhooks
from app.routers.conversations import models_router

# Phase 6 — initialize structured logging FIRST so any startup error from
# tracing (or anything else) emits as JSON. Tracing is independent: if
# Jaeger is unreachable, the configure call quietly returns False and the
# app keeps running.
configure_logging()
configure_tracing()

log = get_logger("app.main")

app = FastAPI(
    title="SYNQ API",
    description="Cross-agent conversation continuity backend",
    version="0.1.0",
)

# Middleware ordering: Starlette runs middlewares in reverse-registration
# order, so the request_id middleware here wraps everything below it
# (including CORS). The request_id is bound BEFORE CORS preflight logging,
# which keeps OPTIONS lines correlatable with their POST counterparts.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Echo the request-id back so the browser can read it (CORS strips
    # non-allowlisted response headers by default).
    expose_headers=["X-Request-Id"],
)

app.include_router(conversations.router)
app.include_router(models_router)
app.include_router(webhooks.router)
app.include_router(files.router)
app.include_router(dashboard.router)
app.include_router(flags.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


log.info("api.boot_complete", environment=settings.environment)
