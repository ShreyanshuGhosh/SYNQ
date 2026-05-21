"""Replay tool — dump the exact request a provider would receive.

Usage:
    python -m app.tools.replay <conversation_id> <target_model>

Outputs the canonical wire-format request that the orchestrator would
hand off to the provider for the given conversation. This is the single
most important debugging surface in the system; per SYNQ_STRUCT
§"Closing Notes": "Build the replay tool early so you can see exactly
what each model is receiving. That tool will save you more debugging
time than any other piece of infrastructure."

The tool never makes a network call. It runs the full planning pipeline
(identity-drift detection, naive truncation, translation) and prints:

  * Model + provider id
  * Drift / truncation diagnostics
  * Token estimate and target window
  * The serialized wire payload — formatted exactly as it would be sent

Read the result with the provider's API docs side-by-side and you will
find the bug.
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
    # ASCII-only so the tool works in cp1252 Windows consoles.
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


async def _run(conv_id: UUID, target_model: str) -> None:
    history = await _load_history(conv_id)

    _print_header("REPLAY")
    print(f"conversation_id : {conv_id}")
    print(f"target_model    : {target_model}")
    print(f"history_turns   : {len(history)}")

    # No user_id check — replay runs locally as the developer.
    plan = await plan_turn(history, target_model)

    _print_header("PLAN")
    print(f"provider             : {plan.provider}")
    print(f"resolved_model_id    : (see wire payload below)")
    print(f"context_window       : {plan.context_window}")
    print(f"prompt_token_estimate: {plan.prompt_token_estimate}")
    print(f"drift_detected       : {plan.drift_detected}")
    print(f"truncated            : {plan.truncated}")
    print(f"dropped_messages     : {plan.dropped_count}")

    # Phase 3 — show how each referenced file resolved for THIS provider.
    # This is the line the user reads to debug "did the new model
    # actually see the image?" questions.
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
                print(f"  shown : [unresolved]")

    _print_header("WIRE PAYLOAD (provider-native format)")
    # Truncate large base64 / file_uri values so the dump stays readable.
    print(json.dumps(_redact_wire(plan.wire_request), indent=2, default=str))

    # Run validate() — this is what the orchestrator calls before
    # `stream_completion`. Surfacing it here means the replay output
    # tells you whether the request would even be sent.
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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.replay",
        description="Dump the exact request a provider would receive.",
    )
    parser.add_argument("conversation_id", type=str)
    parser.add_argument("target_model", type=str)
    args = parser.parse_args()

    try:
        conv_id = UUID(args.conversation_id)
    except ValueError as exc:
        print(f"replay: invalid UUID {args.conversation_id!r}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    asyncio.run(_run(conv_id, args.target_model))


if __name__ == "__main__":
    main()
