#!/usr/bin/env bash
# Container entrypoint for the SYNQ API on Render.
#
# 1. Apply database migrations (idempotent — no-op when already at head).
# 2. Launch uvicorn bound to Render's injected $PORT.
#
# Background jobs (embeddings, file parsing, summaries) run in-process via
# Celery eager mode — see CELERY_EAGER in the Render env — so there is no
# separate worker process to start here.
set -euo pipefail

echo "[start] applying database migrations…"
alembic upgrade head

echo "[start] launching API on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
