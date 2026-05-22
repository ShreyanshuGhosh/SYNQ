"""Phase 4 background workers — embedding, summary, fact extraction.

Three independent Celery tasks feed the artifacts the context engine
reads on every turn:

  * ``embed_message``         — vector index for RAG.
  * ``update_rolling_summary`` — narrative of older turns.
  * ``extract_facts``         — structured KV memory (user_name, etc.).

All three run on the QUEUE Redis instance via the existing celery_app
(see ``celery_app.py``). They are idempotent: re-running them on the
same input produces the same Qdrant points / DB rows. The orchestrator
fires them post-turn; nothing on the request path waits for them.

Per the Phase 4 spec:
  * Summary and fact-extraction use a CHEAP model (Groq Llama 3.1 8B,
    the free replacement for Haiku / gpt-4o-mini called out in the
    architecture). Hard-coded — NOT user-configurable in Phase 4.
  * Embedding uses Mistral mistral-embed (the free replacement for
    OpenAI text-embedding-3-small).
"""

from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import Any
from uuid import UUID

import litellm

from app.config import settings
from app.embeddings import embed_one, embed_texts
from app.vector_store import ensure_collections, upsert_file_chunks, upsert_message
from app.workers.celery_app import celery_app
from app.workers.db_sync import sync_session

logger = logging.getLogger(__name__)


# ── Shared helpers ──────────────────────────────────────────────────────


def _message_text(content: list[dict[str, Any]] | None) -> str:
    """Concatenate every text block in a message's content array.

    Mirrors the canonical-data-model rule "even pure-text messages are
    stored as ``[{type:'text', text:'...'}]``". Non-text blocks are
    represented as their type for embedding purposes — e.g. an image
    block becomes "[image]" — so the vector still encodes that an image
    was present even when the bytes themselves aren't embeddable.
    """
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            txt = block.get("text") or ""
            if txt:
                parts.append(txt)
        elif btype == "image":
            parts.append("[image]")
        elif btype == "file_ref":
            parts.append("[file]")
        elif btype == "tool_use":
            parts.append(f"[tool_use:{block.get('name', 'unknown')}]")
        elif btype == "tool_result":
            parts.append("[tool_result]")
    return "\n".join(parts).strip()


def _cheap_completion(*, model: str, system: str, user: str) -> str | None:
    """Single non-streaming call to the hard-coded cheap model.

    Used by both summary and fact-extract workers. Failure is logged and
    returns ``None`` — both callers treat None as "skip this update".
    """
    api_key = settings.groq_api_key or None
    try:
        resp = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            api_key=api_key,
            api_base="https://api.groq.com/openai/v1",
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        logger.exception("intelligence: cheap completion failed (model=%s)", model)
        return None


# ── 1. embed_message ────────────────────────────────────────────────────


@celery_app.task(
    name="app.workers.intelligence.embed_message", bind=True, max_retries=2
)
def embed_message(self: Any, message_id: str) -> dict[str, Any]:
    """Embed one message into Qdrant ``synq_messages``.

    Idempotent: the point ID is uuid5(namespace, message_id), so a
    second run replaces the existing point in-place — no duplicates.

    Updates ``messages.embedding_status`` to 'done' (success) or
    'failed' (exception). Pending stays pending until the worker picks
    it up — set by the orm default at message insert.
    """
    from app.orm import Message

    ensure_collections()
    mid = UUID(message_id)
    with sync_session() as session:
        row = session.get(Message, mid)
        if row is None:
            logger.warning("embed_message: id=%s missing", mid)
            return {"status": "missing"}
        text = _message_text(row.content)
        if not text:
            row.embedding_status = "done"
            return {"status": "empty_skipped"}
        try:
            vec = embed_one(text)
            upsert_message(
                message_id=str(row.id),
                conversation_id=str(row.conversation_id),
                turn_index=row.turn_index,
                role=row.role,
                text_snippet=text,
                vector=vec,
                model_used_for_embedding=settings.embedding_model,
                created_at=row.created_at.astimezone(timezone.utc).isoformat()
                if row.created_at
                else None,
            )
            row.embedding_status = "done"
            return {"status": "done"}
        except Exception as exc:
            logger.exception("embed_message: id=%s failed", mid)
            row.embedding_status = "failed"
            # Re-raise so Celery records the failure but DON'T retry
            # automatically — most embed failures are deterministic
            # (auth, malformed text). A manual replay is fine.
            raise exc


# ── 1b. embed_file_chunks ───────────────────────────────────────────────


@celery_app.task(
    name="app.workers.intelligence.embed_file_chunks", bind=True, max_retries=2
)
def embed_file_chunks(self: Any, file_id: str) -> dict[str, Any]:
    """Embed all chunks of a parsed file into ``synq_file_chunks``.

    Triggered by the parse worker once chunks are written. Idempotent:
    point id = uuid5(file_id, chunk_id), so a re-run replaces in place.
    """
    from app.orm import File

    ensure_collections()
    fid = UUID(file_id)
    with sync_session() as session:
        row = session.get(File, fid)
        if row is None:
            return {"status": "missing"}
        chunks = list(row.chunks or [])
        if not chunks:
            return {"status": "no_chunks"}
        texts = [str(c.get("text", "")) for c in chunks]
        try:
            vectors = embed_texts(texts)
        except Exception:
            logger.exception("embed_file_chunks: file_id=%s embed failed", fid)
            raise
        records: list[tuple[int, str, int | None, list[float]]] = []
        for c, vec in zip(chunks, vectors):
            cid = int(c.get("chunk_id", 0))
            page = c.get("page")
            page_int = int(page) if isinstance(page, int) else None
            records.append((cid, str(c.get("text", "")), page_int, vec))
        upsert_file_chunks(
            file_id=str(fid),
            user_id=str(row.user_id),
            chunks=records,
        )
        return {"status": "done", "chunks": len(records)}


# ── 2. update_rolling_summary ───────────────────────────────────────────


_SUMMARY_SYSTEM_PROMPT = """You are a summarization assistant. Compress \
the older portion of a chat conversation into a faithful, factual recap.

HARD RULES:
- Output ONLY a bulleted list, one fact or decision per bullet.
- Cite the source turn number for every bullet: "(turn 12)".
- Preserve numbers, dates, file names, model names, identifiers, and \
quoted strings EXACTLY as they appear. Never paraphrase numeric data.
- Do NOT invent or infer details that are not in the supplied turns.
- Do NOT include opinions or stylistic commentary.
- Focus on: decisions made, facts shared, open questions, work in \
progress, named entities (people, projects, tools).
- Omit greetings, acknowledgments, and meta-chatter.
- Keep it under 400 words total.

The current rolling summary (if any) is appended for context — extend, \
do not duplicate."""


_SUMMARY_USER_TEMPLATE = """OLDER TURNS TO SUMMARIZE (turns {start}-{end}):
{turns}

EXISTING SUMMARY (cite turn ranges already covered; do not repeat them):
{existing}

Produce the updated bulleted summary."""


@celery_app.task(
    name="app.workers.intelligence.update_rolling_summary",
    bind=True,
    max_retries=1,
)
def update_rolling_summary(self: Any, conversation_id: str) -> dict[str, Any]:
    """Regenerate ``conversations.rolling_summary`` for older turns.

    "Older" = everything before the verbatim window (last N turns). If
    there are no turns past the window, the task is a no-op.

    Trigger policy (orchestrator-side): runs after every N new turns OR
    on switch event when ``summary_through_turn`` is stale.
    """
    from app.orm import Conversation, Message
    from sqlalchemy import select

    cid = UUID(conversation_id)
    with sync_session() as session:
        conv = session.get(Conversation, cid)
        if conv is None:
            return {"status": "missing"}
        rows = list(
            session.execute(
                select(Message)
                .where(Message.conversation_id == cid)
                .order_by(Message.turn_index.asc())
            )
            .scalars()
            .all()
        )
        if len(rows) <= settings.verbatim_window_turns:
            return {"status": "nothing_to_summarize"}

        older = rows[: -settings.verbatim_window_turns]
        # Skip if we've already covered all of `older` since last run.
        if conv.summary_through_turn >= older[-1].turn_index:
            return {"status": "up_to_date"}

        # Cap the per-call prompt size so the cheap model's token
        # limit (Groq Llama 3.1 8B caps prompts at ~12k tokens on the
        # free tier) is never exceeded. When the older window is
        # bigger than the cap, we send the MOST RECENT chunk of older
        # turns — the existing summary already covers earlier ones.
        cap = 120  # ~12k char-ish budget at the per-turn limits below
        if len(older) > cap:
            older = older[-cap:]

        formatted = _format_turns_for_summary(older)
        prompt = _SUMMARY_USER_TEMPLATE.format(
            start=older[0].turn_index,
            end=older[-1].turn_index,
            turns=formatted,
            existing=(conv.rolling_summary or "(none yet)"),
        )
        summary = _cheap_completion(
            model=settings.summary_model,
            system=_SUMMARY_SYSTEM_PROMPT,
            user=prompt,
        )
        if not summary:
            return {"status": "summary_call_failed"}

        conv.rolling_summary = summary
        conv.summary_through_turn = older[-1].turn_index
        return {
            "status": "updated",
            "through_turn": older[-1].turn_index,
            "summary_chars": len(summary),
        }


def _format_turns_for_summary(rows: list[Any]) -> str:
    lines: list[str] = []
    for r in rows:
        text = _message_text(r.content)
        if not text:
            continue
        # Keep each turn compact — long ones get truncated. The summary
        # model only needs the gist; full text lives in Postgres.
        if len(text) > 1200:
            text = text[:1200] + " ..."
        lines.append(f"[turn {r.turn_index} · {r.role}]\n{text}")
    return "\n\n".join(lines)


# ── 3. extract_facts ────────────────────────────────────────────────────


_FACT_EXTRACTION_SYSTEM_PROMPT = """You are an information-extraction \
assistant. Read the recent chat turns and extract structured facts.

Output MUST be a single JSON object — no prose, no markdown fences. \
Use exactly these top-level keys (omit any key whose value is empty):

{
  "user_name": "string",
  "project_name": "string",
  "tech_stack": ["string", ...],
  "decisions": ["string with optional (turn N) citation", ...],
  "open_questions": ["string", ...],
  "preferences": ["string", ...],
  "constraints": ["string", ...]
}

HARD RULES:
- Output valid JSON only. No backticks, no explanation, no leading text.
- Only include items you can directly support from the turns. Do not \
guess. If nothing was said about a field, omit it entirely.
- Preserve names and numbers verbatim.
- Each list should be short (max 8 items)."""


_FACT_EXTRACTION_USER_TEMPLATE = """RECENT TURNS:
{turns}

EXISTING FACTS (do not duplicate; new items will be merged):
{existing}

Return the JSON object."""


@celery_app.task(
    name="app.workers.intelligence.extract_facts", bind=True, max_retries=1
)
def extract_facts(self: Any, conversation_id: str) -> dict[str, Any]:
    """Pull structured facts from recent turns; merge into extracted_facts.

    Merge policy:
      * Scalar fields (user_name, project_name) overwrite only if empty
        previously or if the new value is non-empty and different.
      * List fields accumulate with dedup (case-insensitive, exact match).
    """
    from app.orm import Conversation, Message
    from sqlalchemy import select

    cid = UUID(conversation_id)
    with sync_session() as session:
        conv = session.get(Conversation, cid)
        if conv is None:
            return {"status": "missing"}
        # Use the verbatim window-ish for fact extraction so context is
        # fresh. The summary worker handles older turns.
        rows = list(
            session.execute(
                select(Message)
                .where(Message.conversation_id == cid)
                .order_by(Message.turn_index.desc())
                .limit(settings.verbatim_window_turns)
            )
            .scalars()
            .all()
        )
        if not rows:
            return {"status": "no_turns"}
        rows = list(reversed(rows))

        formatted = _format_turns_for_summary(rows)
        prompt = _FACT_EXTRACTION_USER_TEMPLATE.format(
            turns=formatted,
            existing=json.dumps(conv.extracted_facts or {}, indent=2),
        )
        raw = _cheap_completion(
            model=settings.fact_extraction_model,
            system=_FACT_EXTRACTION_SYSTEM_PROMPT,
            user=prompt,
        )
        if not raw:
            return {"status": "extraction_call_failed"}
        new_facts = _parse_facts_json(raw)
        if new_facts is None:
            return {"status": "unparseable", "raw_chars": len(raw)}

        merged = _merge_facts(dict(conv.extracted_facts or {}), new_facts)
        conv.extracted_facts = merged
        return {"status": "updated", "fields": list(merged.keys())}


_SCALAR_FIELDS = {"user_name", "project_name"}
_LIST_FIELDS = {
    "tech_stack",
    "decisions",
    "open_questions",
    "preferences",
    "constraints",
}


def _parse_facts_json(raw: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction — strips ``` fences if the model adds them."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].strip()
    # Some small models return prose before the JSON; grab the brace span.
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _merge_facts(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Combine extracted-fact dicts. Lists accumulate; scalars upgrade."""
    out = dict(existing)
    for key, value in new.items():
        if value is None or value == "" or value == []:
            continue
        if key in _SCALAR_FIELDS:
            if not isinstance(value, str):
                continue
            current = out.get(key)
            if not current:
                out[key] = value
        elif key in _LIST_FIELDS:
            if not isinstance(value, list):
                continue
            current_list = list(out.get(key, []))
            seen_lower = {str(x).strip().lower() for x in current_list}
            for item in value:
                if not isinstance(item, str):
                    continue
                lo = item.strip().lower()
                if lo and lo not in seen_lower:
                    current_list.append(item.strip())
                    seen_lower.add(lo)
            # Cap to keep extracted_facts JSONB lean.
            out[key] = current_list[:32]
        else:
            # Forward unknown fields verbatim so prompt updates can add
            # keys without a schema migration.
            out[key] = value
    return out
