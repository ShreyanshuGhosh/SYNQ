"""Text embedding — Mistral mistral-embed via LiteLLM.

The Phase 4 architecture doc names OpenAI text-embedding-3-small as the
default embedder. We have no OpenAI/Anthropic budget (see project memory
+ phase-2/3 decisions) so the equivalent here is Mistral's
``mistral-embed`` on the same "Experiment" free tier the chat path uses.

Dimensions: 1024 (mistral-embed) — set once in ``settings.embedding_dim``
so Qdrant collection creation, point inserts, and search all agree.

This module exposes two callables:

  * ``embed_texts(texts)`` — sync, used by Celery workers.
  * ``aembed_texts(texts)`` — async, used by the context engine when it
    needs to embed the current user message before a RAG search.

Both return ``list[list[float]]`` of length ``len(texts)``. Empty input
short-circuits to an empty list; any per-string failure raises (the
caller decides whether to retry — workers mark embedding_status='failed'
on exception).
"""

from __future__ import annotations

import logging
from typing import Sequence

import litellm

from app.config import settings

logger = logging.getLogger(__name__)


# LiteLLM accepts the bare ``mistral/`` prefix and picks up the API key
# from ``MISTRAL_API_KEY`` env var or the explicit ``api_key`` kwarg.
# Keeping ``api_base`` explicit guards against LiteLLM auto-routing to a
# different host if the default ever changes.
_API_BASE = "https://api.mistral.ai/v1"


def _ensure_strs(texts: Sequence[str]) -> list[str]:
    """Drop empties and replace None with '' — mistral-embed rejects both."""
    return [t if isinstance(t, str) and t.strip() else " " for t in texts]


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Sync embed. Returns one vector per input, same order.

    The result vector dim is ``settings.embedding_dim``; callers should
    not introspect — they just hand it to Qdrant.
    """
    if not texts:
        return []
    cleaned = _ensure_strs(texts)
    resp = litellm.embedding(
        model=settings.embedding_model,
        input=cleaned,
        api_key=settings.mistral_api_key or None,
        api_base=_API_BASE,
    )
    # LiteLLM normalizes both OpenAI- and Mistral-shaped responses to
    # {data: [{embedding: [...]}, ...]}.
    data = getattr(resp, "data", None) or resp["data"]
    out: list[list[float]] = []
    for item in data:
        vec = item["embedding"] if isinstance(item, dict) else item.embedding
        out.append(list(vec))
    if len(out) != len(cleaned):
        raise RuntimeError(
            f"embeddings: expected {len(cleaned)} vectors, got {len(out)}"
        )
    return out


async def aembed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Async variant for the request path. Uses LiteLLM's async embedding."""
    if not texts:
        return []
    cleaned = _ensure_strs(texts)
    resp = await litellm.aembedding(
        model=settings.embedding_model,
        input=cleaned,
        api_key=settings.mistral_api_key or None,
        api_base=_API_BASE,
    )
    data = getattr(resp, "data", None) or resp["data"]
    out: list[list[float]] = []
    for item in data:
        vec = item["embedding"] if isinstance(item, dict) else item.embedding
        out.append(list(vec))
    if len(out) != len(cleaned):
        raise RuntimeError(
            f"embeddings: expected {len(cleaned)} vectors, got {len(out)}"
        )
    return out


def embed_one(text: str) -> list[float]:
    """Convenience: embed a single string."""
    vecs = embed_texts([text])
    return vecs[0]


async def aembed_one(text: str) -> list[float]:
    vecs = await aembed_texts([text])
    return vecs[0]
