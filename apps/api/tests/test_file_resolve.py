"""Unit tests for per-adapter resolve_file behavior.

These tests exercise the resolution layer that the orchestrator hands
to translate_messages. They do NOT make network calls — the S3 download
is monkeypatched and Gemini's Files API upload returns ``None`` so the
Gemini path degrades to inline bytes.

The two end-to-end scenarios called out in the Phase 3 spec
(image-on-gemini-then-switch and 50-page-PDF chunking) live in
``test_phase3_e2e.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.adapters import _gemini_files
from app.adapters._resolve import default_resolve
from app.adapters.gemini_adapter import GeminiAdapter
from app.adapters.groq_adapter import GroqAdapter
from app.adapters.mistral_adapter import MistralAdapter
from app.adapters import _resolve


def _make_file_row(**overrides):
    """Mock SQLAlchemy `files` row shape — only fields resolve_file reads."""
    base = dict(
        id=uuid4(),
        mime_type="image/png",
        size_bytes=12_000,
        storage_url="http://minio:9000/synq-files/files/abc/test.png",
        extracted_text=None,
        description="A red square on a white background.",
        parse_status="done",
        original_filename="test.png",
        error=None,
        chunks=[],
        user_id=uuid4(),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Text-only (Mistral) ─────────────────────────────────────────────────


def test_mistral_image_substitutes_description():
    """Non-vision target receives the description text, not raw bytes."""
    adapter = MistralAdapter(model="mistral-small-latest", provider_model_id="mistral-small-latest")
    rf = default_resolve(_make_file_row(), capabilities=adapter.capabilities)
    assert rf.strategy == "description"
    assert rf.inline_bytes is None
    assert "red square" in (rf.description_text or "")


def test_mistral_pdf_substitutes_extracted_text():
    """Documents always go through extracted_text on every adapter."""
    adapter = MistralAdapter(model="mistral-small-latest", provider_model_id="mistral-small-latest")
    row = _make_file_row(
        mime_type="application/pdf",
        extracted_text="Hello World\nLine 2",
        description=None,
        original_filename="readme.pdf",
    )
    rf = default_resolve(row, capabilities=adapter.capabilities)
    assert rf.strategy == "description"
    assert "Hello World" in (rf.description_text or "")
    assert "readme.pdf" in (rf.description_text or "")


# ── Vision-capable Groq ────────────────────────────────────────────────


def test_groq_vision_inlines_small_image(monkeypatch):
    """A 12KB image under the 20MB cap takes the inline-bytes path."""
    monkeypatch.setattr(
        _resolve, "download_bytes", lambda key: b"\x89PNG\r\n\x1a\nfake"
    )
    adapter = GroqAdapter(
        model="groq-llama-vision",
        provider_model_id="meta-llama/llama-4-scout-17b-16e-instruct",
    )
    rf = default_resolve(_make_file_row(), capabilities=adapter.capabilities)
    assert rf.strategy == "inline"
    assert rf.inline_bytes is not None
    assert rf.description_text is None


def test_groq_text_model_falls_back_to_description():
    """A Groq model without vision (llama-3.1-8b-instant) keeps text-only behavior."""
    adapter = GroqAdapter(
        model="groq-llama-3.1-8b", provider_model_id="llama-3.1-8b-instant"
    )
    rf = default_resolve(_make_file_row(), capabilities=adapter.capabilities)
    assert rf.strategy == "description"
    assert rf.inline_bytes is None


# ── Failed parse degrades gracefully ───────────────────────────────────


def test_failed_parse_surfaces_user_visible_error():
    """A failed parse short-circuits to a description chip the model sees."""
    adapter = MistralAdapter(model="mistral-small-latest", provider_model_id="mistral-small-latest")
    row = _make_file_row(
        parse_status="failed",
        description=None,
        error={"message": "pdfplumber: corrupt file"},
    )
    rf = default_resolve(row, capabilities=adapter.capabilities)
    assert rf.strategy == "description"
    assert "pdfplumber" in (rf.description_text or "")


# ── Gemini Files API path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gemini_image_prefers_files_api(monkeypatch):
    """When the Files API returns a URI, the adapter records it on
    ResolvedFile (and NOT inline bytes)."""
    monkeypatch.setattr(
        "app.adapters.gemini_adapter.download_bytes",
        lambda key: b"\x89PNG\r\n\x1a\nfake",
    )
    monkeypatch.setattr(
        _gemini_files,
        "resolve_for_gemini",
        lambda *a, **kw: "files/generated_uri_for_test",
    )
    # The Gemini adapter pulls resolve_for_gemini from its own module
    # namespace, not _gemini_files.* — patch there too.
    monkeypatch.setattr(
        "app.adapters.gemini_adapter.resolve_for_gemini",
        lambda *a, **kw: "files/generated_uri_for_test",
    )
    adapter = GeminiAdapter(model="gemini-2.5-flash", provider_model_id="gemini-2.5-flash")
    rf = await adapter.resolve_file(_make_file_row())
    assert rf.strategy == "files_api"
    assert rf.files_api_uri == "files/generated_uri_for_test"
    # inline_bytes is carried alongside the URI so stream_completion can
    # send base64 to LiteLLM (which cannot auth against Files API URIs).
    assert rf.inline_bytes is not None
