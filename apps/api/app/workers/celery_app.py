"""Celery app — broker on the QUEUE Redis instance.

Per SYNQ_STRUCT §"Tier 10 — Data Plane": Redis runs as two instances so
the task backlog never evicts cached context. The Celery app points
at REDIS_QUEUE_URL exclusively. Anything touching the cache (rate
limiter, future circuit breakers) uses REDIS_URL.

Beat is wired but empty — Phase 4 adds the summary worker on a real
schedule. Today it just confirms the schedule plumbing works.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "synq",
    broker=settings.redis_queue_url,
    backend=settings.redis_queue_url,
    include=["app.workers.tasks", "app.workers.intelligence"],
)

celery_app.conf.update(
    # Windows does not support billiard's prefork pool (shared-memory
    # semaphores raise PermissionError). Use `solo` so `celery worker`
    # works without flags. On Linux/macOS in prod, override with
    # CELERYD_POOL=prefork or pass --pool=prefork on the CLI.
    worker_pool="solo",
    # Tasks should fail visibly. The default of swallowing exceptions is
    # the wrong behavior for a pipeline whose only purpose is to record
    # parse outcomes back to Postgres.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Per Phase 3 spec — long docs can take >60s for OCR; bump the
    # default soft limit so tesseract on a 50-pager doesn't kill the task.
    task_soft_time_limit=600,
    task_time_limit=900,
    # Make sure JSON is the only acceptable payload (no pickle in prod).
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Beat schedule: empty for Phase 3. Phase 4 will add:
    #   - synq.workers.summary.regenerate_rolling_summary every 10 turns
    #   - synq.workers.embedder.embed_pending_messages every minute
    beat_schedule={
        # Heartbeat probe — proves beat is alive without doing real work.
        "noop_heartbeat": {
            "task": "app.workers.tasks.heartbeat",
            "schedule": crontab(minute="*/30"),
        },
    },
)
