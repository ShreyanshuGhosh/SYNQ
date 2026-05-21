"""S3 / R2 / MinIO object storage client.

One module, one boto3 client, used by both the API (uploads) and the
Celery worker (downloads for parsing + adapter resolution).

Hard rule from SYNQ_STRUCT §"Multimodal Mismatches": originals stored in
S3 are NEVER auto-deleted. Only user-initiated GDPR cascade (Phase 6)
removes them. This module exposes no `delete` helper for that reason —
forgetting to call it is impossible if it doesn't exist.

Keys are random UUIDs (not user-supplied filenames) to keep listings
opaque if the bucket policy ever leaks.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

import boto3
from botocore.client import Config

from app.config import settings

logger = logging.getLogger(__name__)


def _client() -> "boto3.session.Session.client":  # type: ignore[name-defined]
    """Lazy boto3 S3 client. MinIO needs path-style addressing; AWS/R2
    accept it. `signature_version=s3v4` works for all three."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint or None,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",  # MinIO ignores this; R2/S3 need something.
    )


def build_key(file_id: UUID, filename: str | None) -> str:
    """Deterministic key from the row's UUID; filename is decorative.

    Schema: ``files/<uuid>/<safe-filename>``. The leading prefix keeps
    everything file-related under one logical folder so a future bucket
    policy can scope to it.
    """
    safe = "blob"
    if filename:
        safe = filename.replace("/", "_").replace("\\", "_")[:160] or "blob"
    return f"files/{file_id}/{safe}"


def upload_fileobj(stream: BinaryIO, *, key: str, content_type: str | None) -> str:
    """Stream `stream` to S3 under `key`. Returns the storage URL.

    The storage URL is the canonical reference we persist on
    files.storage_url. For MinIO it's a regular http URL through the
    endpoint; for S3/R2 the same shape works. Phase 6 will switch to
    pre-signed URLs for direct browser access.
    """
    extra: dict[str, str] = {}
    if content_type:
        extra["ContentType"] = content_type
    _client().upload_fileobj(stream, settings.s3_bucket, key, ExtraArgs=extra)
    return f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{key}"


def download_bytes(key: str) -> bytes:
    """Fetch raw bytes — used by the Celery worker and adapters."""
    buf = BytesIO()
    _client().download_fileobj(settings.s3_bucket, key, buf)
    return buf.getvalue()


def key_from_storage_url(storage_url: str) -> str:
    """Inverse of `upload_fileobj`'s URL builder.

    Storage URLs are not stable across deploys (the endpoint may differ),
    but the suffix after ``<bucket>/`` is the key. That's what we strip.
    """
    needle = f"/{settings.s3_bucket}/"
    idx = storage_url.find(needle)
    if idx == -1:
        # Defensive fallback: assume the whole tail is the key.
        return storage_url.rsplit("/", 1)[-1]
    return storage_url[idx + len(needle) :]


def new_file_id() -> UUID:
    return uuid4()
