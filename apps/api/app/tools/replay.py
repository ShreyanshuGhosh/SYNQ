"""Replay tool — dump the exact request a provider would receive.

Usage:
    python -m app.tools.replay <conversation_id> <target_model>

Outputs the canonical wire-format request that the orchestrator would
hand off to the provider for the given conversation. This is the single
most important debugging surface in the system; per ARCHITECTURE
§"Closing Notes": "Build the replay tool early so you can see exactly
what each model is receiving. That tool will save you more debugging
time than any other piece of infrastructure."

The tool never makes a network completion call. It runs the full
planning pipeline (drift detection, six-part context assembly with RAG,
file resolution, translation) and prints:

  * Model + provider id, context window
  * Drift / compression diagnostics
  * Phase 4 — section breakdown with per-section token counts
  * Phase 4 — RAG hits with scores and turn citations
  * Resolved files per provider
  * The serialized wire payload — formatted as it would be sent

Section dump format follows the Phase 4 spec:

    === FACTS (124 tokens) ===
    === SUMMARY (450 tokens) ===
    === RETRIEVED (3 chunks, 890 tokens) ===
      [score 0.82] turn 47: "we decided to use Qdrant because..."
    === RECENT (15 turns, 8200 tokens) ===
    === TOTAL: 9664 tokens, target window 200000 ===
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Message as MessageModel
from app.orchestrator import plan_turn
from app.orm import Conversation, Message


async def _load_history(conv_id: UUID) -> list[MessageModel]:
    async with SessionLocal() as s:
        conv = (
            await s.execute(select(Conversation).where(Conversation.id == conv_id))
        ).scalar_one_or_none()
        if conv is None:
            raise SystemExit(f"replay: conversation {conv_id} not found")
        rows = list(
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
    return [MessageModel.model_validate(r) for r in rows]


def _print_header(text: str) -> None:
    bar = "-" * len(text)
    print(f"\n{text}\n{bar}")


def _redact_wire(node):  # type: ignore[no-untyped-def]
    """Truncate base64 image data inside a wire payload so the dump is
    readable. Keeps the shape intact so the rest of the JSON is honest."""
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            if k in ("data",) and isinstance(v, str) and len(v) > 80:
                out[k] = f"<base64 {len(v)} chars>"
            elif k in ("url",) and isinstance(v, str) and v.startswith("data:") and len(v) > 120:
                out[k] = f"data:...<truncated {len(v)} chars>"
            else:
                out[k] = _redact_wire(v)
        return out
    if isinstance(node, list):
        return [_redact_wire(x) for x in node]
    return node


def _print_sections(plan) -> None:  # type: ignore[no-untyped-def]
    """Phase 4 — render the section-by-section breakdown."""
    built = plan.built_context
    if built is None:
        print("(no context_engine BuiltContext attached — Phase 4 disabled?)")
        return

    if built.passthrough:
        print(
            f"PASSTHROUGH — full conversation fit under threshold "
            f"({built.total_token_estimate} tokens of "
            f"{built.context_window}-token window)."
        )
    for s in built.sections:
        if not s.included:
            print(f"=== {s.name} (skipped: {s.note}) ===")
            continue
        extra = ""
        if s.item_count:
            unit = (
                "chunks" if s.name == "RETRIEVED"
                else "turns" if s.name in {"RECENT", "FULL_CONVERSATION"}
                else "items"
            )
            extra = f", {s.item_count} {unit}"
        note = f"  // {s.note}" if s.note else ""
        print(f"=== {s.name} ({s.token_estimate} tokens{extra}) ==={note}")

    if built.rag_hits:
        print()
        print("  RAG hits (top-K, ranked):")
        for h in built.rag_hits:
            snippet = h.snippet.replace("\n", " ").strip()
            if len(snippet) > 100:
                snippet = snippet[:100] + "..."
            print(f"    [score {h.score:.2f}] turn {h.turn_index} ({h.role}): \"{snippet}\"")

    print()
    print(
        f"=== TOTAL: {built.total_token_estimate} tokens, "
        f"target window {built.context_window} ==="
    )


async def _run(
    conv_id: UUID,
    target_model: str,
    *,
    show_cost: bool = False,
    completion_tokens_guess: int = 500,
) -> None:
    history = await _load_history(conv_id)

    _print_header("REPLAY")
    print(f"conversation_id : {conv_id}")
    print(f"target_model    : {target_model}")
    print(f"history_turns   : {len(history)}")

    # Pass conversation_id so the context engine can pull pinned
    # context, extracted facts, and rolling summary, AND so the RAG
    # search can filter by conversation.
    plan = await plan_turn(history, target_model, conversation_id=conv_id)

    _print_header("PLAN")
    print(f"provider             : {plan.provider}")
    print(f"resolved_model_id    : (see wire payload below)")
    print(f"context_window       : {plan.context_window}")
    print(f"prompt_token_estimate: {plan.prompt_token_estimate}")
    print(f"drift_detected       : {plan.drift_detected}")
    print(f"compressed           : {plan.truncated}")
    print(f"older_turns_dropped  : {plan.dropped_count}")

    _print_header("CONTEXT ENGINE — SECTIONS")
    _print_sections(plan)

    _print_header("RESOLVED FILES")
    if not plan.resolved_files:
        print("(no files referenced)")
    else:
        for fid, rf in plan.resolved_files.items():
            print(f"file_id : {fid}")
            print(f"  mime  : {rf.mime_type}")
            print(f"  strat : {rf.strategy}{(' (' + rf.note + ')') if rf.note else ''}")
            if rf.inline_bytes is not None:
                kb = len(rf.inline_bytes) / 1024
                print(f"  shown : [IMAGE BYTES: {kb:.1f}KB inline]")
            elif rf.files_api_uri:
                print(f"  shown : [FILES API URI: {rf.files_api_uri}]")
            elif rf.description_text:
                snippet = rf.description_text.strip().splitlines()
                head = snippet[0] if snippet else ""
                tail = f" ... ({len(rf.description_text)} chars)" if len(rf.description_text) > 80 else ""
                print(f"  shown : [DESCRIPTION SUBSTITUTED: {head[:80]}{tail}]")
            else:
                print("  shown : [unresolved]")

    _print_header("WIRE PAYLOAD (provider-native format)")
    print(json.dumps(_redact_wire(plan.wire_request), indent=2, default=str))

    validation = await plan.adapter.validate(plan.wire_request)
    _print_header("VALIDATION")
    print(f"ok       : {validation.ok}")
    if validation.warnings:
        print("warnings :")
        for w in validation.warnings:
            print(f"  - {w}")
    if validation.errors:
        print("errors   :")
        for e in validation.errors:
            print(f"  - {e}")

    if show_cost:
        _print_cost_estimate(plan, completion_tokens_guess=completion_tokens_guess)


def _print_cost_estimate(plan, completion_tokens_guess: int = 500) -> None:  # type: ignore[no-untyped-def]
    """Phase 5 — append a cost estimate using the cost-meter price table.

    We don't know the actual completion size at planning time, so we
    guess 500 tokens — typical short-to-medium response. Tweak via the
    --completion-tokens flag if you're testing a long-form response.
    """
    from app.workers.cost_meter import PRICE_TABLE, estimate_cost_usd

    prompt = plan.prompt_token_estimate
    completion = completion_tokens_guess
    cost = estimate_cost_usd(plan.model, prompt, completion)
    price = PRICE_TABLE.get(plan.model)

    _print_header("COST ESTIMATE")
    if price is None:
        print(f"(no price entry for {plan.model} — defaulted to $0)")
    print(f"prompt_tokens     : {prompt}")
    print(f"completion_guess  : {completion}")
    print(f"Estimated cost if sent to {plan.model}: ${cost:.4f}")
    if price:
        print(
            f"  rate: ${price['prompt'] * 1_000_000:.3f}/1M prompt, "
            f"${price['completion'] * 1_000_000:.3f}/1M completion"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.replay",
        description="Dump the exact request a provider would receive.",
    )
    parser.add_argument("conversation_id", type=str)
    parser.add_argument("target_model", type=str)
    parser.add_argument(
        "--force-compression",
        action="store_true",
        help=(
            "Shrink the compression trigger ratio for this run so the "
            "six-part assembly engages even on small/synthetic chats. "
            "Useful for inspecting the RAG path against fixture data."
        ),
    )
    parser.add_argument(
        "--show-cost",
        action="store_true",
        help=(
            "Append a cost estimate using the cost-meter price table. "
            "Phase 5 — useful for comparing models pre-send."
        ),
    )
    parser.add_argument(
        "--completion-tokens",
        type=int,
        default=500,
        help="Assumed completion token count for the cost estimate (default 500).",
    )
    args = parser.parse_args()

    try:
        conv_id = UUID(args.conversation_id)
    except ValueError as exc:
        print(f"replay: invalid UUID {args.conversation_id!r}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.force_compression:
        from app.config import settings as _s

        _s.compression_trigger_ratio = 0.0001

    asyncio.run(
        _run(
            conv_id,
            args.target_model,
            show_cost=args.show_cost,
            completion_tokens_guess=args.completion_tokens,
        )
    )


if __name__ == "__main__":
    main()
