"""Qdrant access layer — collections, upserts, search.

Two collections are owned by this module:

  * ``synq_messages``    — one point per message turn.
      payload = {conversation_id, message_id, turn_index,
                 model_used_for_embedding, text_snippet, role, created_at}
      vector  = mistral-embed of the concatenated text content.

  * ``synq_file_chunks`` — one point per chunk produced by the Phase 3
      parse worker.
      payload = {file_id, chunk_id, page, text_snippet, user_id}
      vector  = mistral-embed of the chunk text.

Both use cosine distance (mistral-embed vectors are L2-normalized but
cosine reads slightly cleaner in scores). Point IDs are deterministic
UUIDv5 derived from (collection, primary_key) so re-running the
embedding worker on the same message never duplicates a point.

The client is constructed lazily and cached. Sync API only — workers run
synchronously and the context engine's one read happens via
``run_in_executor`` (see ``context_engine``). qdrant-client does ship an
async variant but it's a separate dep tree and not worth the surface
area for the single read site.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings

logger = logging.getLogger(__name__)


# Deterministic namespaces so the IDs the embed worker writes are the
# same IDs a later re-run computes — that's how "idempotent upserts"
# works without a separate dedupe table.
_NS_MESSAGES = uuid.UUID("4d6cb4a4-1f7d-4d57-9b1a-72e9e0c8b91b")
_NS_FILE_CHUNKS = uuid.UUID("8e4c4f7a-0c0a-4bd6-9b41-8a44f8b4b7c2")


@dataclass
class SearchHit:
    """One Qdrant search result."""

    id: str
    score: float
    payload: dict[str, Any]


# ── Client ──────────────────────────────────────────────────────────────

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """Lazy singleton. Reuses HTTP connections across worker tasks."""
    global _client
    if _client is None:
        _client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            prefer_grpc=False,
            timeout=10,
        )
    return _client


def ensure_collections() -> None:
    """Create the two collections if absent. Safe to call repeatedly."""
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    vectors_config = qm.VectorParams(
        size=settings.embedding_dim,
        distance=qm.Distance.COSINE,
    )
    if settings.qdrant_collection_messages not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection_messages,
            vectors_config=vectors_config,
        )
        # Index conversation_id for filterable searches — every read
        # narrows to a single conversation.
        client.create_payload_index(
            collection_name=settings.qdrant_collection_messages,
            field_name="conversation_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection_messages,
            field_name="turn_index",
            field_schema=qm.PayloadSchemaType.INTEGER,
        )
        logger.info("qdrant: created collection %s", settings.qdrant_collection_messages)
    if settings.qdrant_collection_file_chunks not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection_file_chunks,
            vectors_config=vectors_config,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection_file_chunks,
            field_name="file_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=settings.qdrant_collection_file_chunks,
            field_name="user_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        logger.info(
            "qdrant: created collection %s", settings.qdrant_collection_file_chunks
        )


# ── Deterministic point IDs ─────────────────────────────────────────────


def message_point_id(message_id: str) -> str:
    """uuid5(messages-namespace, message_id) — re-runs collapse to one point."""
    return str(uuid.uuid5(_NS_MESSAGES, message_id))


def file_chunk_point_id(file_id: str, chunk_id: int) -> str:
    return str(uuid.uuid5(_NS_FILE_CHUNKS, f"{file_id}:{chunk_id}"))


# ── Upserts ─────────────────────────────────────────────────────────────


def upsert_message(
    *,
    message_id: str,
    conversation_id: str,
    turn_index: int,
    role: str,
    text_snippet: str,
    vector: Sequence[float],
    model_used_for_embedding: str,
    created_at: str | None = None,
) -> str:
    """Insert/replace one message point. Returns the point id."""
    point_id = message_point_id(message_id)
    payload: dict[str, Any] = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "turn_index": turn_index,
        "role": role,
        "text_snippet": text_snippet[:500],
        "model_used_for_embedding": model_used_for_embedding,
    }
    if created_at is not None:
        payload["created_at"] = created_at
    get_client().upsert(
        collection_name=settings.qdrant_collection_messages,
        points=[qm.PointStruct(id=point_id, vector=list(vector), payload=payload)],
    )
    return point_id


def upsert_file_chunks(
    *,
    file_id: str,
    user_id: str,
    chunks: Iterable[tuple[int, str, int | None, Sequence[float]]],
) -> list[str]:
    """Bulk upsert chunks for one file.

    ``chunks`` is an iterable of (chunk_id, text, page, vector). Returns
    the point IDs that were written.
    """
    points: list[qm.PointStruct] = []
    ids: list[str] = []
    for chunk_id, text, page, vector in chunks:
        pid = file_chunk_point_id(file_id, chunk_id)
        ids.append(pid)
        points.append(
            qm.PointStruct(
                id=pid,
                vector=list(vector),
                payload={
                    "file_id": file_id,
                    "user_id": user_id,
                    "chunk_id": chunk_id,
                    "page": page,
                    "text_snippet": text[:500],
                },
            )
        )
    if not points:
        return []
    get_client().upsert(
        collection_name=settings.qdrant_collection_file_chunks,
        points=points,
    )
    return ids


# ── Search ──────────────────────────────────────────────────────────────


def search_messages(
    *,
    query_vector: Sequence[float],
    conversation_id: str,
    top_k: int,
    exclude_turn_indices: Iterable[int] = (),
) -> list[SearchHit]:
    """RAG read for the context engine.

    Filters by ``conversation_id`` so a user can only retrieve from
    their own thread (combined with conversation-row authorization
    above, this is the second layer of access control).

    ``exclude_turn_indices`` lifts the verbatim window — turns already
    shown verbatim shouldn't also appear in <retrieved_context>.
    """
    exclude = list(exclude_turn_indices)
    must_filters: list[qm.FieldCondition] = [
        qm.FieldCondition(
            key="conversation_id", match=qm.MatchValue(value=conversation_id)
        )
    ]
    must_not_filters: list[qm.FieldCondition] = []
    if exclude:
        must_not_filters.append(
            qm.FieldCondition(key="turn_index", match=qm.MatchAny(any=exclude))
        )
    qfilter = qm.Filter(must=must_filters, must_not=must_not_filters)

    # qdrant-client >=1.13 deprecated `.search()` in favor of
    # `.query_points()` which returns a Response object with `.points`.
    # We use the newer API and unwrap the points list.
    try:
        resp = get_client().query_points(
            collection_name=settings.qdrant_collection_messages,
            query=list(query_vector),
            query_filter=qfilter,
            limit=top_k,
            with_payload=True,
        )
        hits = resp.points
    except Exception:
        logger.exception(
            "qdrant: search failed (conversation=%s, k=%d); returning empty",
            conversation_id,
            top_k,
        )
        return []

    out: list[SearchHit] = []
    for h in hits:
        out.append(
            SearchHit(
                id=str(h.id),
                score=float(h.score),
                payload=dict(h.payload or {}),
            )
        )
    return out
