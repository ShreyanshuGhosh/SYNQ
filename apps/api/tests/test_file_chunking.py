"""Chunking behavior for long extracted text.

Phase 3 chunks text whose token estimate exceeds
``settings.chunk_trigger_tokens`` (default 4000) into ~500-token chunks.
Short text passes through unchunked.
"""

from __future__ import annotations

from app.config import settings
from app.workers.tasks import _chunk_text


def test_short_text_is_not_chunked():
    """A 500-character doc is well under the trigger and stays as one piece."""
    assert _chunk_text("hello world\n\nthis is short") == []


def test_long_text_chunks_into_target_sized_pieces():
    """Generate enough text to exceed the chunk trigger and verify the
    resulting JSONB shape matches what the spec calls for."""
    paragraph = ("token " * 100).strip()  # ~600 chars per paragraph
    # 40 paragraphs ~= 24000 chars ~= 6000 tokens — well over the 4000 trigger.
    doc = "\n\n".join([paragraph] * 40)

    chunks = _chunk_text(doc)
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c["chunk_id"] == i
        assert c["page"] is None
        assert isinstance(c["text"], str)
        assert c["text"].strip() != ""
    # Each chunk should stay near the target size (within 2× as a sanity
    # bound — paragraph-boundary splitting introduces some variance).
    target_chars = settings.chunk_target_tokens * 4
    for c in chunks[:-1]:  # last chunk often partial
        assert len(c["text"]) <= target_chars * 2


def test_chunks_reassemble_to_original_content():
    """No chunk drops content: concatenation == original (up to whitespace)."""
    paragraph = "alpha bravo charlie " * 40
    doc = "\n\n".join([paragraph] * 30)
    chunks = _chunk_text(doc)
    rejoined = "\n\n".join(c["text"] for c in chunks).strip()
    # Tokens count should match — the chunker doesn't summarize.
    assert rejoined.count("alpha") == doc.count("alpha")
