"""Synchronous DB session for Celery tasks.

The rest of the API uses asyncpg (async SQLAlchemy). Celery's worker
model is synchronous by default and mixing async loops into Celery's
process model is fragile (each task would need its own event loop).

So workers get their own engine via the psycopg sync driver — same
Postgres, same schema, same ORM classes; just a different transport.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=4,
    max_overflow=8,
)

SyncSessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


@contextmanager
def sync_session() -> Iterator[Session]:
    s = SyncSessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
