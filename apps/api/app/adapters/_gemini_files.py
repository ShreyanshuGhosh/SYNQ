"""Gemini Files API uploader with Redis URI cache.

Gemini's documented retention for uploaded files is 48 hours. On every
adapter resolution we either:
    1. Read a cached URI from Redis (cache hit), or
    2. Upload the bytes to Gemini's Files API and cache the URI.

The Files API URI is what we embed in the wire payload — `file_data:
{file_uri: ..., mime_type: ...}` — rather than the base64 bytes. This
matters for large images: inline base64 inflates token usage 33% and
hits Gemini's per-request payload caps.
"""

from __future__ import annotations

import io
import logging

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "gemini_files_uri:"


def _redis() -> "redis.Redis":
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def cache_key(file_id: str) -> str:
    return f"{_CACHE_PREFIX}{file_id}"


def get_cached_uri(file_id: str) -> str | None:
    try:
        return _redis().get(cache_key(file_id))
    except Exception:
        logger.exception("gemini_files: redis get failed for %s", file_id)
        return None


def set_cached_uri(file_id: str, uri: str) -> None:
    try:
        _redis().setex(
            cache_key(file_id), settings.gemini_file_ttl_seconds, uri
        )
    except Exception:
        logger.exception("gemini_files: redis set failed for %s", file_id)


def upload_to_gemini(
    raw: bytes,
    *,
    mime_type: str,
    display_name: str | None = None,
) -> str | None:
    """Upload `raw` to Gemini's Files API. Returns the URI or None.

    Uses ``google-genai`` (the unified Google SDK). The call is
    synchronous — we run it from the SYNC resolve path inside the
    orchestrator. None on any failure so the resolver can degrade to
    a description fallback.
    """
    if not settings.gemini_api_key:
        logger.info("gemini_files: GEMINI_API_KEY not set; skipping upload")
        return None
    try:
        from google import genai
    except Exception:
        logger.warning("gemini_files: google-genai not installed; skipping upload")
        return None

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        # The SDK accepts a file-like and a config dict.
        uploaded = client.files.upload(
            file=io.BytesIO(raw),
            config={
                "mime_type": mime_type,
                "display_name": display_name or "synq-upload",
            },
        )
        uri = getattr(uploaded, "uri", None) or getattr(uploaded, "name", None)
        if uri:
            return str(uri)
        logger.warning("gemini_files: upload returned no URI")
        return None
    except Exception:
        logger.exception("gemini_files: upload failed")
        return None


def resolve_for_gemini(file_id: str, raw: bytes, mime_type: str) -> str | None:
    """Cache-first lookup → upload on miss → cache the new URI."""
    cached = get_cached_uri(file_id)
    if cached:
        return cached
    uri = upload_to_gemini(raw, mime_type=mime_type, display_name=file_id)
    if uri:
        set_cached_uri(file_id, uri)
    return uri
