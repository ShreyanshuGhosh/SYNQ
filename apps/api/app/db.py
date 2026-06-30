"""SQLAlchemy engine, session, and declarative base."""

from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Common declarative base for all ORM models."""


def _async_url_and_connect_args() -> tuple[str, dict[str, object]]:
    """Split out libpq-only query params asyncpg cannot accept.

    Managed Postgres providers (Neon, Supabase, RDS) hand out URLs with
    ``?sslmode=require`` (and sometimes ``channel_binding``). Those are
    psycopg/libpq keywords — asyncpg rejects them and instead wants TLS
    enabled via ``connect_args={"ssl": ...}``. The sync Alembic engine
    keeps the libpq params (psycopg understands them); only the async
    runtime engine needs this translation, so we do it here.
    """
    url = settings.async_database_url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))

    connect_args: dict[str, object] = {}
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # libpq-only; asyncpg has no equivalent

    # Any sslmode that requires encryption → turn on TLS for asyncpg.
    # "disable"/"allow"/"prefer" are treated as "no forced TLS" (local dev).
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = True

    clean_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return clean_url, connect_args


_async_url, _connect_args = _async_url_and_connect_args()

engine = create_async_engine(
    _async_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
