"""Synthetic 300-turn fixture — verifies Phase 4 context engine end-to-end.

Usage:
    python -m app.tools.synthetic_fixture --turns 300 [--user-id <uuid>]

What it does:

  1. Creates one Conversation row owned by ``--user-id`` (or the first
     row in ``users`` if not given).
  2. Inserts ``--turns`` synthetic alternating user/assistant Messages.
     Around turn 30 it plants a deliberate "anchor" fact ("we decided to
     use Qdrant because ...") that is far outside the verbatim window —
     the RAG-retrieval test depends on this being recoverable.
  3. Marks ``model_used`` on early assistant turns as the Claude-equivalent
     (Groq Llama 3.1 8B in our free-tier swap) and later as the
     Gemini-equivalent — so identity drift is detected.
  4. Synchronously runs ``embed_message`` on every inserted row so the
     Qdrant index is populated without waiting for the worker queue.
  5. Calls ``update_rolling_summary`` and ``extract_facts`` once each.
  6. Replays the conversation with target_model=gemini-2.5-flash and
     prints whether the anchor turn (turn 30) was retrieved by RAG.

Use the printed ``conversation_id`` with the replay tool to dump the
full context dump that the user asked for.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Message as MessageModel
from app.orchestrator import plan_turn
from app.orm import Conversation, Message, User
from app.workers.intelligence import (
    embed_message,
    extract_facts,
    update_rolling_summary,
)

logger = logging.getLogger("synthetic_fixture")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# A small bank of generic chat-flavored content. The fixture's job is
# to look like a long, varied conversation — not to be coherent. Every
# turn gets a unique numeric tag so the embedder produces distinct
# vectors instead of collapsing similar text.
_USER_TOPICS = [
    "What's the difference between {a} and {b}?",
    "Can you explain how {x} works?",
    "I'm thinking about using {x} for {y}. Any concerns?",
    "Compare {a} vs {b} for a Python backend.",
    "Help me debug a {x} issue I'm seeing.",
    "What are best practices for {x} in production?",
]
_NOUNS = [
    "Postgres", "Redis", "Kafka", "Celery", "FastAPI", "Pydantic", "asyncpg",
    "Qdrant", "Pinecone", "Weaviate", "Elasticsearch", "ClickHouse",
    "OpenTelemetry", "Sentry", "Stripe", "Clerk", "Auth0", "Vault",
    "Docker", "Kubernetes", "Vercel", "Cloudflare", "S3", "MinIO",
]
_ASSISTANT_FORMATS = [
    "{x} is generally chosen when {y}. The main tradeoff is {z}.",
    "Short answer: {x}. Long answer: depends on {y} and {z}.",
    "Here are three points: 1) {x}. 2) {y}. 3) {z}.",
    "I'd recommend {x} for your case. Watch out for {y}.",
]


_FREE_CLAUDE_ANALOG = "groq-llama-3.1-8b"
_FREE_GEMINI_DEFAULT = "gemini-2.5-flash"


def _user_text(i: int) -> str:
    a, b, x, y, z = (
        _NOUNS[i % len(_NOUNS)],
        _NOUNS[(i + 3) % len(_NOUNS)],
        _NOUNS[(i + 7) % len(_NOUNS)],
        _NOUNS[(i + 11) % len(_NOUNS)],
        _NOUNS[(i + 13) % len(_NOUNS)],
    )
    template = _USER_TOPICS[i % len(_USER_TOPICS)]
    body = template.format(a=a, b=b, x=x, y=y)
    return f"[turn {i}] {body}"


def _assistant_text(i: int) -> str:
    x, y, z = (
        _NOUNS[(i + 1) % len(_NOUNS)],
        _NOUNS[(i + 5) % len(_NOUNS)],
        _NOUNS[(i + 9) % len(_NOUNS)],
    )
    template = _ASSISTANT_FORMATS[i % len(_ASSISTANT_FORMATS)]
    return f"[turn {i}] " + template.format(x=x, y=y, z=z)


# The anchor turns the RAG test must surface. These are deliberately
# made distinctive so a search for "Qdrant" or "embedding model" lights
# them up clearly even against 300 turns of noise.
_ANCHOR_TURN_USER = (
    "[turn 30] We need to pick a vector database. What do you think about Qdrant "
    "specifically — is it suitable for SYNQ's RAG use case?"
)
_ANCHOR_TURN_ASSISTANT = (
    "[turn 31] We decided to use Qdrant because it has first-class payload "
    "filtering, cosine distance support, and runs comfortably in Docker for "
    "local development. The mistral-embed model produces 1024-dim vectors that "
    "Qdrant handles natively. This is the canonical decision for the project."
)


def _new_message(
    conv_id: UUID,
    turn_index: int,
    role: str,
    text: str,
    model_used: str | None,
) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=conv_id,
        turn_index=turn_index,
        role=role,
        content=[{"type": "text", "text": text}],
        model_used=model_used,
        token_counts=None,
        cost_usd=None,
        embedding_status="pending",
        idempotency_key=None,
        created_at=datetime.now(timezone.utc),
    )


async def _resolve_user_id(explicit: UUID | None) -> UUID:
    """Return ``explicit`` if given, else first user in the table.

    The fixture refuses to invent a user — every real row has a Clerk
    mapping, so we attach to one that exists rather than break that
    invariant.
    """
    if explicit is not None:
        return explicit
    async with SessionLocal() as s:
        first = (
            await s.execute(select(User).limit(1))
        ).scalar_one_or_none()
        if first is None:
            raise SystemExit(
                "synthetic_fixture: no users in DB. Sign in once via the web app "
                "first so a Clerk row gets created, then re-run."
            )
        return first.id


async def _insert_synthetic_conversation(
    user_id: UUID, num_turns: int
) -> tuple[UUID, list[UUID]]:
    """Insert one conversation and ``num_turns`` messages. Returns ids."""
    async with SessionLocal() as s:
        conv = Conversation(
            id=uuid4(),
            user_id=user_id,
            title=f"Synthetic fixture — {num_turns} turns @ {datetime.now().isoformat(timespec='seconds')}",
            current_model=_FREE_CLAUDE_ANALOG,
        )
        s.add(conv)
        await s.flush()
        conv_id = conv.id

        msg_ids: list[UUID] = []
        for i in range(num_turns):
            if i == 30:
                text = _ANCHOR_TURN_USER
                role = "user"
                model = None
            elif i == 31:
                text = _ANCHOR_TURN_ASSISTANT
                role = "assistant"
                model = _FREE_CLAUDE_ANALOG
            elif i % 2 == 0:
                text = _user_text(i)
                role = "user"
                model = None
            else:
                text = _assistant_text(i)
                role = "assistant"
                # Flip to Gemini halfway through to exercise identity drift.
                model = (
                    _FREE_CLAUDE_ANALOG if i < num_turns // 2 else _FREE_GEMINI_DEFAULT
                )
            m = _new_message(conv_id, i, role, text, model)
            s.add(m)
            msg_ids.append(m.id)
        await s.commit()
    return conv_id, msg_ids


def _run_workers_sync(conv_id: UUID, msg_ids: list[UUID]) -> dict[str, Any]:
    """Call worker functions inline (no Celery hop) so the fixture is
    self-contained — useful in dev where the worker may not be running."""
    embed_ok = 0
    embed_fail = 0
    for mid in msg_ids:
        try:
            # Bypass Celery's .delay() and call the wrapped function
            # directly. The bound `self` arg is satisfied by passing the
            # task itself; embed_message reads only `message_id`.
            embed_message.run(str(mid))
            embed_ok += 1
        except Exception:
            embed_fail += 1
            logger.exception("fixture: embed failed for %s", mid)
    summary_result = update_rolling_summary.run(str(conv_id))
    facts_result = extract_facts.run(str(conv_id))
    return {
        "embed_ok": embed_ok,
        "embed_failed": embed_fail,
        "summary": summary_result,
        "facts": facts_result,
    }


async def _validate_rag(conv_id: UUID, force_compression: bool) -> dict[str, Any]:
    """Replay against Gemini and confirm anchor turn 31 is retrieved.

    When ``force_compression`` is true, the trigger ratio is pushed
    down to a value that guarantees the six-part assembly runs against
    the synthetic fixture's short turns. Without this, Gemini's 1M
    context window means 300 short turns trivially fit verbatim and
    the RAG path is never exercised.
    """
    if force_compression:
        # Temporarily shrink the threshold for THIS process only.
        settings.compression_trigger_ratio = 0.0001

    # Add a final user turn that asks specifically about the anchor topic.
    async with SessionLocal() as s:
        rows = list(
            (
                await s.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.turn_index.desc())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
        last_idx = rows[0].turn_index if rows else -1
        question = _new_message(
            conv_id,
            last_idx + 1,
            "user",
            "Which vector database did we pick, and why? Specifically reference the decision we made earlier.",
            None,
        )
        s.add(question)
        await s.commit()

    async with SessionLocal() as s:
        history_rows = list(
            (
                await s.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.turn_index.asc())
                )
            )
            .scalars()
            .all()
        )
    history = [MessageModel.model_validate(r) for r in history_rows]

    plan = await plan_turn(
        history, _FREE_GEMINI_DEFAULT, conversation_id=conv_id
    )
    built = plan.built_context
    anchor_hit = False
    if built is not None:
        for h in built.rag_hits:
            if h.turn_index in (30, 31):
                anchor_hit = True
                break
    return {
        "compressed": plan.truncated,
        "drift_detected": plan.drift_detected,
        "rag_hits": [
            {
                "turn": h.turn_index,
                "score": h.score,
                "role": h.role,
                "snippet": h.snippet[:120],
            }
            for h in (built.rag_hits if built else [])
        ],
        "anchor_retrieved": anchor_hit,
        "total_tokens": built.total_token_estimate if built else None,
    }


async def _main(num_turns: int, user_id: UUID | None, force_compression: bool) -> None:
    uid = await _resolve_user_id(user_id)
    logger.info("fixture: creating %d-turn conversation for user=%s", num_turns, uid)
    conv_id, msg_ids = await _insert_synthetic_conversation(uid, num_turns)
    logger.info("fixture: conversation_id=%s (messages=%d)", conv_id, len(msg_ids))

    logger.info("fixture: running workers inline (this calls Mistral + Groq APIs)...")
    worker_result = _run_workers_sync(conv_id, msg_ids)
    logger.info("fixture: worker result = %s", worker_result)

    logger.info(
        "fixture: validating RAG with cross-model question (force_compression=%s)...",
        force_compression,
    )
    validation = await _validate_rag(conv_id, force_compression)
    logger.info("fixture: validation = %s", validation)

    print()
    print("=" * 60)
    print(f"Synthetic fixture conversation_id: {conv_id}")
    print("=" * 60)
    print(f"Anchor (turn 30/31) retrieved by RAG: {validation['anchor_retrieved']}")
    print(f"Compression engaged: {validation['compressed']}")
    print(f"Identity drift detected: {validation['drift_detected']}")
    print(f"Estimated total tokens: {validation['total_tokens']}")
    print()
    print("Next: run the replay tool against this conversation to dump sections:")
    print(f"  python -m app.tools.replay {conv_id} {_FREE_GEMINI_DEFAULT}")
    print()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.tools.synthetic_fixture")
    p.add_argument("--turns", type=int, default=300)
    p.add_argument("--user-id", type=str, default=None)
    p.add_argument(
        "--force-compression",
        action="store_true",
        help=(
            "Shrink the compression trigger ratio so the six-part assembly "
            "runs even on the short synthetic turns. Necessary to exercise "
            "the RAG path against a 300-turn synthetic conversation."
        ),
    )
    args = p.parse_args()
    uid = UUID(args.user_id) if args.user_id else None
    # Touch settings so unrelated config errors fail fast at startup.
    _ = settings.qdrant_url
    asyncio.run(_main(args.turns, uid, args.force_compression))


if __name__ == "__main__":
    main()
