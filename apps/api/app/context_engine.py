"""Context engine — the six-part compression assembly.

This is the centerpiece of Phase 4. It replaces the naive
drop-oldest truncation that lived in ``orchestrator.plan_turn`` with
the algorithm specified in ARCHITECTURE §"The Context Engine".

Pure function. Given (conversation_id, target_model, user_message) and
read-only DB / Qdrant access, ``build_context`` returns a deterministic
list of canonical messages. Mutation of conversation state (turn
inserts, summary updates, fact updates) happens elsewhere — never here.

The six-part assembly, in this exact order (per the spec):

  1. Pinned context        — user-marked must-include items.
  2. Extracted facts       — structured KV memory.
  3. Rolling summary       — narrative of older turns.
  4. RAG-retrieved chunks  — Qdrant search vs current user message.
  5. Verbatim recent turns — last N turns in full.
  6. Current user message  — the question we are about to answer.

Each section is tagged so the model knows what it's reading:
``<facts>...</facts>``, ``<rolling_summary>...</rolling_summary>``,
``<retrieved_context>...</retrieved_context>``,
``<recent_turns>...</recent_turns>``.

Fast path: when the full conversation fits under
``context_window * compression_trigger_ratio``, we skip compression and
return the full canonical history (passthrough).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.adapters import ProviderAdapter, adapter_for
from app.config import settings
from app.core.flags import flag
from app.core.logging import get_logger
from app.core.tracing import get_tracer, set_attributes
from app.embeddings import aembed_one
from app.models import (
    ContentBlock,
    FileRefBlock,
    ImageBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from app.vector_store import SearchHit, ensure_collections, search_messages

log = get_logger(__name__)
logger = log  # back-compat: existing code uses ``logger.exception(...)``
_tracer = get_tracer("app.context_engine")


def _end_span(span: Any) -> None:
    """Best-effort span end. Tolerant of the no-op tracer."""
    if span is None:
        return
    try:
        span.end()
    except Exception:
        pass


SYSTEM_PROMPT_TEMPLATE = (
    "You are continuing a conversation. Earlier context is summarized below. "
    "Treat <facts> as established truth, <rolling_summary> as a narrative recap, "
    "<retrieved_context> as relevant older exchanges, and <recent_turns> as the "
    "immediate conversation. Respond to the user's latest message."
)


# ── Diagnostics ─────────────────────────────────────────────────────────


@dataclass
class SectionInfo:
    """Per-section accounting surfaced to the replay tool."""

    name: str
    token_estimate: int
    included: bool = True
    item_count: int = 0
    note: str = ""


@dataclass
class RagDebug:
    """One RAG hit, surfaced as-is to the replay tool."""

    score: float
    turn_index: int
    role: str
    snippet: str


@dataclass
class BuiltContext:
    """The product of ``build_context``.

    ``messages`` is the list the adapter receives. Everything else is
    diagnostics for the replay tool (and, eventually, telemetry).
    """

    messages: list[Message]
    sections: list[SectionInfo] = field(default_factory=list)
    rag_hits: list[RagDebug] = field(default_factory=list)
    total_token_estimate: int = 0
    context_window: int = 0
    passthrough: bool = False
    drift_detected: bool = False
    system_prompt: str = SYSTEM_PROMPT_TEMPLATE


# ── Pure helpers ────────────────────────────────────────────────────────


_CHARS_PER_TOKEN = 4
_SENTINEL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _char_estimate_blocks(blocks: list[ContentBlock]) -> int:
    total = 0
    for b in blocks:
        if isinstance(b, TextBlock):
            total += len(b.text)
        elif isinstance(b, (ImageBlock, FileRefBlock)):
            total += 32  # cheap placeholder
        elif isinstance(b, ToolUseBlock):
            total += len(json.dumps(b.input)) + len(b.name)
        elif isinstance(b, ToolResultBlock):
            total += 64
    return total // _CHARS_PER_TOKEN


def _char_estimate_messages(messages: list[Message]) -> int:
    total = 0
    for m in messages:
        total += _char_estimate_blocks(list(m.content))
    return total


def _text_of(block: ContentBlock) -> str:
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, ImageBlock):
        return "[image]"
    if isinstance(block, FileRefBlock):
        return "[file]"
    if isinstance(block, ToolUseBlock):
        return f"[tool_use:{block.name}]"
    if isinstance(block, ToolResultBlock):
        return "[tool_result]"
    return ""


def _message_text(m: Message) -> str:
    return "\n".join(_text_of(b) for b in m.content).strip()


def _synthetic(role: str, text: str, turn_index: int = -1) -> Message:
    """Build an in-memory Message for assembled context sections."""
    return Message(
        id=_SENTINEL_UUID,
        conversation_id=_SENTINEL_UUID,
        turn_index=turn_index,
        role=role,
        content=[TextBlock(text=text)],
        model_used=None,
        token_counts=None,
        cost_usd=None,
        embedding_status="pending",
        idempotency_key=None,
        created_at=datetime.now(timezone.utc),
    )


# ── Section assemblers ──────────────────────────────────────────────────


def _render_facts(extracted: dict[str, Any]) -> str:
    """Compact JSON inside the <facts> tag. Stable key order for diffs."""
    if not extracted:
        return ""
    return json.dumps(extracted, indent=2, sort_keys=True, ensure_ascii=False)


def _render_pinned(pinned: list[dict[str, Any]]) -> str:
    """Flatten pinned items to a human-readable bulleted list.

    Pinned items are stored as canonical content blocks. We render text
    blocks verbatim; non-text blocks degrade to their type marker (the
    full file/image flows through the normal message channel — pinning
    is about retention across compression, not duplication of bytes).
    """
    if not pinned:
        return ""
    lines: list[str] = []
    for i, item in enumerate(pinned, start=1):
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            lines.append(f"- {item.get('text', '').strip()}")
        elif kind == "image":
            lines.append(f"- [pinned image file_id={item.get('file_id')}]")
        elif kind == "file_ref":
            lines.append(
                f"- [pinned file file_id={item.get('file_id')} sel={item.get('selection') or '*'}]"
            )
        else:
            lines.append(f"- [pinned {kind}]")
    return "\n".join(lines).strip()


def _format_rag_hits(hits: list[SearchHit]) -> str:
    """Format Qdrant hits into the <retrieved_context> body."""
    if not hits:
        return ""
    lines: list[str] = []
    for h in hits:
        turn = h.payload.get("turn_index", "?")
        role = h.payload.get("role", "?")
        snippet = (h.payload.get("text_snippet") or "").strip()
        lines.append(f"[turn {turn} · {role} · score {h.score:.2f}]\n{snippet}")
    return "\n\n".join(lines)


# ── The build function ─────────────────────────────────────────────────


async def build_context(
    *,
    conversation_id: UUID | None,
    history: list[Message],
    target_model: str,
    user_message: Message | None,
    pinned_context: list[dict[str, Any]] | None = None,
    extracted_facts: dict[str, Any] | None = None,
    rolling_summary: str | None = None,
    drift_detected: bool = False,
    adapter: ProviderAdapter | None = None,
) -> BuiltContext:
    """Assemble the messages that get sent to ``target_model``.

    Pure: does not write to Postgres or Qdrant. Reads Qdrant for the
    RAG section. Caller is the orchestrator (or the replay tool).

    ``history`` should be the full canonical message list IN ORDER,
    INCLUDING the current ``user_message`` as its final entry. The
    function will pull ``user_message`` out for the RAG query and the
    verbatim slot; passing it both inside ``history`` and as the
    ``user_message`` arg is the convention from the orchestrator.
    """
    adapter = adapter or adapter_for(target_model)
    target_window = adapter.context_window
    threshold = int(target_window * settings.compression_trigger_ratio)

    pinned_context = list(pinned_context or [])
    extracted_facts = dict(extracted_facts or {})

    # ── Phase 6 — feature-flag tuning ────────────────────────────────
    # compression_v2: tighter verbatim window + more RAG chunks. The
    # context engine uses these resolved values throughout the build.
    verbatim_n = settings.verbatim_window_turns
    rag_k = settings.rag_top_k
    if flag("compression_v2"):
        verbatim_n = 8
        rag_k = 12

    # The Phase 6 spec asks for a custom "context_engine.build" span with
    # rich attributes. We open the span manually (rather than wrapping the
    # whole function in a ``with`` block) so the existing function body
    # keeps its indentation; ``_finish_span`` sets the final attrs at every
    # return site.
    build_span = _tracer.start_span("context_engine.build")
    set_attributes(
        build_span,
        conversation_id=str(conversation_id) if conversation_id else None,
        target_model=target_model,
        provider=adapter.provider,
        total_messages=len(history),
        verbatim_window_turns=verbatim_n,
        rag_top_k=rag_k,
        compression_v2=flag("compression_v2"),
        aggressive_rag=flag("aggressive_rag"),
    )

    # ── Fast path: small enough → passthrough ───────────────────────
    char_est = _char_estimate_messages(history)
    fits_without_compression = char_est <= threshold
    set_attributes(
        build_span,
        fits_without_compression=fits_without_compression,
        total_tokens_before=char_est,
    )
    if fits_without_compression:
        msgs = _maybe_prepend_drift(history, drift_detected)
        set_attributes(build_span, total_tokens_after=char_est, passthrough=True)
        _end_span(build_span)
        return BuiltContext(
            messages=msgs,
            sections=[
                SectionInfo(
                    name="FULL_CONVERSATION",
                    token_estimate=char_est,
                    item_count=len(history),
                    note="passthrough — under compression threshold",
                )
            ],
            total_token_estimate=char_est,
            context_window=target_window,
            passthrough=True,
            drift_detected=drift_detected,
        )

    # ── Compression assembly ────────────────────────────────────────

    # Compression actually kicked in — log it so the operator can grep
    # for "compression.triggered" across the day.
    log.info(
        "compression.triggered",
        conversation_id=str(conversation_id) if conversation_id else None,
        tokens_before=char_est,
        strategy="compression_v2" if flag("compression_v2") else "default",
        verbatim_window_turns=verbatim_n,
        rag_top_k=rag_k,
    )

    sections: list[SectionInfo] = []
    rag_debug: list[RagDebug] = []

    # The verbatim slot is the last N turns. The "current user message"
    # is the last entry of history; we keep it in the verbatim slot too
    # since the spec keeps last 10-20 turns as the immediate context.
    # (verbatim_n already resolved above with feature-flag tuning.)
    verbatim_messages = history[-verbatim_n:] if history else []
    older_messages = history[:-verbatim_n] if len(history) > verbatim_n else []
    excluded_turns = {m.turn_index for m in verbatim_messages}

    # 1. Pinned context
    pinned_text = _render_pinned(pinned_context)
    if pinned_text:
        section_msg = _synthetic(
            "system",
            f"<pinned_context>\n{pinned_text}\n</pinned_context>",
        )
        sections.append(
            SectionInfo(
                name="PINNED",
                token_estimate=_char_estimate_messages([section_msg]),
                item_count=len(pinned_context),
            )
        )
    else:
        section_msg = None
        sections.append(
            SectionInfo(
                name="PINNED", token_estimate=0, included=False, note="empty"
            )
        )
    pinned_msg = section_msg

    # 2. Extracted facts
    facts_text = _render_facts(extracted_facts)
    facts_msg: Message | None = None
    if facts_text:
        facts_msg = _synthetic(
            "system", f"<facts>\n{facts_text}\n</facts>"
        )
        sections.append(
            SectionInfo(
                name="FACTS",
                token_estimate=_char_estimate_messages([facts_msg]),
                item_count=len(extracted_facts),
            )
        )
    else:
        sections.append(
            SectionInfo(name="FACTS", token_estimate=0, included=False, note="empty")
        )

    # 3. Rolling summary (only if older turns were dropped)
    summary_msg: Message | None = None
    if older_messages and rolling_summary:
        summary_msg = _synthetic(
            "system",
            f"<rolling_summary>\n{rolling_summary.strip()}\n</rolling_summary>",
        )
        sections.append(
            SectionInfo(
                name="SUMMARY",
                token_estimate=_char_estimate_messages([summary_msg]),
                note=f"covers up through older turn {older_messages[-1].turn_index}",
            )
        )
    else:
        sections.append(
            SectionInfo(
                name="SUMMARY",
                token_estimate=0,
                included=False,
                note=(
                    "no older turns"
                    if not older_messages
                    else "no rolling summary stored yet"
                ),
            )
        )

    # 4. RAG retrieval
    rag_msg: Message | None = None
    if (
        conversation_id is not None
        and user_message is not None
        and older_messages
    ):
        query_text = _message_text(user_message)
        if query_text:
            rag_span = _tracer.start_span("context_engine.rag_retrieve")
            set_attributes(
                rag_span,
                query_tokens=len(query_text) // _CHARS_PER_TOKEN,
                top_k=rag_k,
            )
            try:
                ensure_collections()
                query_vec = await aembed_one(query_text)
                hits = await asyncio.to_thread(
                    search_messages,
                    query_vector=query_vec,
                    conversation_id=str(conversation_id),
                    top_k=rag_k,
                    exclude_turn_indices=excluded_turns,
                )
            except Exception:
                logger.exception(
                    "rag.retrieve_failed",
                    conversation_id=str(conversation_id),
                )
                hits = []
            # Phase 6 — aggressive_rag: also embed the rolling summary and
            # do a second retrieval pass against it. Merge results by
            # score (highest first), dedupe by (turn_index, role).
            if flag("aggressive_rag") and rolling_summary:
                try:
                    summary_vec = await aembed_one(rolling_summary)
                    summary_hits = await asyncio.to_thread(
                        search_messages,
                        query_vector=summary_vec,
                        conversation_id=str(conversation_id),
                        top_k=max(2, rag_k // 2),
                        exclude_turn_indices=excluded_turns,
                    )
                except Exception:
                    summary_hits = []
                if summary_hits:
                    seen = {
                        (h.payload.get("turn_index"), h.payload.get("role"))
                        for h in hits
                    }
                    for sh in summary_hits:
                        key = (sh.payload.get("turn_index"), sh.payload.get("role"))
                        if key in seen:
                            continue
                        hits.append(sh)
                        seen.add(key)
                    hits.sort(key=lambda h: h.score, reverse=True)
                    hits = hits[:rag_k]
            top_score = hits[0].score if hits else 0.0
            set_attributes(
                rag_span,
                chunks_retrieved=len(hits),
                top_score=float(top_score),
                aggressive_rag=flag("aggressive_rag"),
            )
            _end_span(rag_span)
            log.info(
                "rag.retrieved",
                conversation_id=str(conversation_id),
                chunks_found=len(hits),
                top_score=float(top_score),
            )
            if hits:
                rag_body = _format_rag_hits(hits)
                rag_msg = _synthetic(
                    "system",
                    f"<retrieved_context>\n{rag_body}\n</retrieved_context>",
                )
                for h in hits:
                    rag_debug.append(
                        RagDebug(
                            score=h.score,
                            turn_index=int(h.payload.get("turn_index", -1)),
                            role=str(h.payload.get("role", "?")),
                            snippet=str(h.payload.get("text_snippet", ""))[:200],
                        )
                    )
                sections.append(
                    SectionInfo(
                        name="RETRIEVED",
                        token_estimate=_char_estimate_messages([rag_msg]),
                        item_count=len(hits),
                    )
                )
            else:
                sections.append(
                    SectionInfo(
                        name="RETRIEVED",
                        token_estimate=0,
                        included=False,
                        note="no hits",
                    )
                )
        else:
            sections.append(
                SectionInfo(
                    name="RETRIEVED",
                    token_estimate=0,
                    included=False,
                    note="empty query",
                )
            )
    else:
        sections.append(
            SectionInfo(
                name="RETRIEVED",
                token_estimate=0,
                included=False,
                note="no older turns to retrieve from",
            )
        )

    # 5. Verbatim recent window
    recent_intro: Message | None = None
    if verbatim_messages:
        recent_intro = _synthetic(
            "system",
            f"<recent_turns count=\"{len(verbatim_messages)}\">",
        )
        recent_outro = _synthetic("system", "</recent_turns>")
        sections.append(
            SectionInfo(
                name="RECENT",
                token_estimate=_char_estimate_messages(verbatim_messages),
                item_count=len(verbatim_messages),
            )
        )
    else:
        recent_outro = None
        sections.append(
            SectionInfo(
                name="RECENT", token_estimate=0, included=False, note="empty"
            )
        )

    # 6. Current user message — already lives at the tail of verbatim.
    sections.append(
        SectionInfo(
            name="CURRENT_USER",
            token_estimate=_char_estimate_messages(
                [user_message] if user_message is not None else []
            ),
            item_count=1 if user_message is not None else 0,
            note="last entry of <recent_turns>",
        )
    )

    # Assemble in spec order. The "system framing" prompt sits at the
    # very top; adapters that take a separate `system` param will lift
    # it via `translate_messages`, others embed it as a system role.
    framing = _synthetic("system", SYSTEM_PROMPT_TEMPLATE)
    out: list[Message] = [framing]
    if pinned_msg is not None:
        out.append(pinned_msg)
    if facts_msg is not None:
        out.append(facts_msg)
    if summary_msg is not None:
        out.append(summary_msg)
    if rag_msg is not None:
        out.append(rag_msg)
    if recent_intro is not None:
        out.append(recent_intro)
        out.extend(verbatim_messages)
    if recent_outro is not None:
        out.append(recent_outro)

    if drift_detected:
        out = _maybe_prepend_drift(out, drift_detected)

    total_estimate = _char_estimate_messages(out)

    set_attributes(
        build_span,
        total_tokens_after=total_estimate,
        passthrough=False,
        rag_hits=len(rag_debug),
    )
    _end_span(build_span)

    return BuiltContext(
        messages=out,
        sections=sections,
        rag_hits=rag_debug,
        total_token_estimate=total_estimate,
        context_window=target_window,
        passthrough=False,
        drift_detected=drift_detected,
    )


_DRIFT_NOTE_TEXT = (
    "Continuing this conversation. Earlier responses were from a different model. "
    "Refer to the previous discussion as 'the previous conversation', not as your "
    "own prior statements."
)


def _maybe_prepend_drift(
    messages: list[Message], drift_detected: bool
) -> list[Message]:
    if not drift_detected:
        return list(messages)
    return [_synthetic("system", _DRIFT_NOTE_TEXT)] + list(messages)
