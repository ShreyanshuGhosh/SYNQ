"""Celery workers — Phase 3.

The worker pool lives under ``apps/api/app/workers/`` per the Phase 3
spec. The Celery app is defined in ``celery_app.py`` and tasks live in
``tasks.py``. Start the worker with::

    cd apps/api
    uv run celery -A app.workers.celery_app worker --loglevel=info

And beat (currently no scheduled jobs, but wired for Phase 4)::

    uv run celery -A app.workers.celery_app beat --loglevel=info
"""
