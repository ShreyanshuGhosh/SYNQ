# SYNQ API — production image for Render (free tier, 512MB).
#
# Runs the FastAPI app with uvicorn. Background jobs run in-process via
# Celery eager mode (set CELERY_EAGER=true in the Render env) so we don't
# need a second worker container — that keeps us inside the free RAM/hours
# budget. Tesseract is installed so the Phase 3 OCR path works.

FROM python:3.12-slim

# System deps:
#   tesseract-ocr  → Phase 3 image OCR (pytesseract shells out to it)
#   libpq5         → psycopg/asyncpg runtime
#   curl           → container HEALTHCHECK
# --no-install-recommends keeps the image small for faster cold starts.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv — fast, reproducible installs from the committed uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Install into the system interpreter (no extra venv layer in-container).
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# Install dependencies first (cached layer) — only re-runs when the lock
# or project metadata changes, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now the application code + migrations.
COPY . .
RUN uv sync --frozen --no-dev

# Render injects $PORT at runtime; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Migrations run on boot inside start.sh, then uvicorn takes over.
RUN chmod +x ./start.sh
CMD ["./start.sh"]
