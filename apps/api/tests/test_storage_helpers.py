"""storage.py URL <-> key round-trip and helper tests.

Pure-function tests; no boto3, no MinIO. These guard against the very
common bug where storage_url renames break adapter download paths.
"""

from __future__ import annotations

from uuid import uuid4

from app.config import settings
from app.storage import build_key, key_from_storage_url


def test_build_key_includes_uuid_and_safe_filename():
    fid = uuid4()
    key = build_key(fid, "weird/name with spaces.pdf")
    assert str(fid) in key
    assert "/" not in key.split("/", 2)[-1]  # filename slashes were collapsed


def test_build_key_handles_missing_filename():
    fid = uuid4()
    key = build_key(fid, None)
    assert key.endswith("/blob")


def test_key_from_storage_url_roundtrips():
    fid = uuid4()
    key = build_key(fid, "doc.pdf")
    storage_url = f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{key}"
    assert key_from_storage_url(storage_url) == key


def test_key_from_storage_url_fallback_on_missing_bucket():
    """If the storage URL doesn't include the configured bucket name, the
    tail of the URL is treated as the key — a soft fallback so legacy URLs
    from a renamed bucket still work."""
    fid = uuid4()
    storage_url = f"http://random.example.com/some-other-bucket/files/{fid}/x.pdf"
    out = key_from_storage_url(storage_url)
    assert out  # not empty
