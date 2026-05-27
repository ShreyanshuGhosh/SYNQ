"""Replay tool — dump the exact request a provider would receive.

Usage:
    python -m app.tools.replay <conversation_id> [target_model]
    python -m app.tools.replay <conversation_id> --dry-run
    python -m app.tools.replay <conversation_id> --trace

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

Phase 6 additions:
  * ``--trace`` opens the Jaeger search URL for this conversation_id.
    The URL is always printed; the flag controls whether the browser
    actually opens.
  * ``--dry-run`` walks the full fallback chain and prints a
    section/token/cost summary per provider — answers "which provider
    is cheapest for this conversation right now?".

Both Phase 6 additions are read-only: the tool never writes to the DB,
never queues a Celery task, never makes a real API call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser
from typing import Any
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Message as MessageModel
from app.orchestrator import plan_turn
from app.orm import Conversation, Message


# Windows consoles default to cp1252 and crash on the U+2192 arrow and other
# non-ASCII characters used in the formatted output. Force UTF-8 once at
# module import so the tool is safe to run from PowerShell / cmd.exe.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


_JAEGER_BASE = "http://localhost:16686"
_SERVICE_NAME = "context-switcher-api"


def jaeger_search_url(conversation_id: str | UUID) -> str:
    """Stable Jaeger query URL filtered to a conversation_id tag."""
    tags = json.dumps({"conversation_id": str(conversation_id)})
    return (
        f"{_JAEGER_BASE}/search?service={_SERVICE_NAME}&tags={quote(tags)}"
    )


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
            elif (
                k in ("url",)
                and isinstance(v, str)
                and v.startswith("data:")
                and len(v) > 120
            ):
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
    trace: bool = False,
) -> None:
    history = await _load_history(conv_id)

    _print_header("REPLAY")
    print(f"conversation_id : {conv_id}")
    print(f"target_model    : {target_model}")
    print(f"history_turns   : {len(history)}")

    # Phase 6 — always print the Jaeger search URL. Open in the browser
    # only when --trace is passed.
    trace_url = jaeger_search_url(conv_id)
    print(f"jaeger_traces   : {trace_url}")
    if trace:
        try:
            webbrowser.open(trace_url)
        except Exception:
            # Headless environments fail silently — the URL is already printed.
            pass

    plan = await plan_turn(history, target_model, conversation_id=conv_id)

    _print_header("PLAN")
    print(f"provider             : {plan.provider}")
    print("resolved_model_id    : (see wire payload below)")
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
                tail = (
                    f" ... ({len(rf.description_text)} chars)"
                    if len(rf.description_text) > 80
                    else ""
                )
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
    """Phase 5 — append a cost estimate using the cost-meter price table."""
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


# ── Phase 6 — multi-provider dry-run simulation ────────────────────────


async def _resolve_file_strategies(plan) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    """Bucket the resolved files into (image_inline, pdf_text, other)."""
    image_inline = 0
    text_subs = 0
    other = 0
    for _fid, rf in (plan.resolved_files or {}).items():
        if rf.inline_bytes is not None:
            image_inline += 1
        elif rf.description_text:
            text_subs += 1
        else:
            other += 1
    return image_inline, text_subs, other


async def _dry_run(conv_id: UUID, completion_tokens_guess: int) -> None:
    """Walk the fallback chain and print a per-provider section/token/cost row.

    Read-only: every step here uses the SAME plan_turn the live request
    path uses, but never calls validate/stream_completion. No DB or task
    side-effects.
    """
    from app.config import settings
    from app.router import circuit_breaker
    from app.router.provider_router import _parse_chain
    from app.workers.cost_meter import PRICE_TABLE, estimate_cost_usd

    chain = _parse_chain()
    if not chain:
        print("(no FALLBACK_CHAIN configured)")
        return

    history = await _load_history(conv_id)
    _print_header(f"DRY-RUN — simulating switch for {conv_id} ({len(history)} turns)")
    print(f"jaeger_traces : {jaeger_search_url(conv_id)}")
    print()
    print(f"fallback_chain: {' → '.join(chain)}")
    print()

    healthy_found = False

    for model in chain:
        # Skip degraded providers per the live router behavior.
        from app.adapters import adapter_for

        try:
            provider = adapter_for(model).provider
        except Exception:
            print(f"→ {model} (UNKNOWN MODEL — skipping)")
            continue

        breaker_state = await circuit_breaker.get_state(provider)
        if breaker_state.state == "degraded":
            print(f"→ {model} (DEGRADED — skipping)")
            print()
            continue

        if healthy_found:
            print(f"→ {model} (would not be reached — earlier provider is healthy)")
            print()
            continue

        try:
            plan = await plan_turn(history, model, conversation_id=conv_id)
        except Exception as exc:
            print(f"→ {model} (plan failed: {exc})")
            print()
            continue

        print(f"→ {model}")
        built = plan.built_context
        if built is not None:
            for s in built.sections:
                if not s.included:
                    continue
                if s.name == "RETRIEVED":
                    top = (
                        max((h.score for h in built.rag_hits), default=0.0)
                        if built.rag_hits
                        else 0.0
                    )
                    print(
                        f"  [RETRIEVED]  {s.item_count} chunks · "
                        f"{s.token_estimate} tokens · top score {top:.2f}"
                    )
                elif s.name == "FACTS":
                    print(f"  [FACTS]      {s.token_estimate} tokens")
                elif s.name == "SUMMARY":
                    print(f"  [SUMMARY]    {s.token_estimate} tokens")
                elif s.name == "PINNED":
                    print(f"  [PINNED]     {s.token_estimate} tokens")
                elif s.name == "RECENT":
                    print(
                        f"  [RECENT]     {s.item_count} turns · "
                        f"{s.token_estimate} tokens"
                    )
                elif s.name == "FULL_CONVERSATION":
                    print(
                        f"  [FULL]       {s.item_count} turns · "
                        f"{s.token_estimate} tokens (passthrough)"
                    )
            pct = (
                100.0 * built.total_token_estimate / built.context_window
                if built.context_window
                else 0.0
            )
            print(
                f"  [TOTAL]      {built.total_token_estimate} / "
                f"{built.context_window} tokens ({pct:.1f}%)"
            )

        # File strategy summary.
        img, text_subs, other = await _resolve_file_strategies(plan)
        if img or text_subs or other:
            parts = []
            if img:
                parts.append(f"{img} image{'s' if img != 1 else ''} as bytes")
            if text_subs:
                parts.append(f"{text_subs} as text")
            if other:
                parts.append(f"{other} unresolved")
            print(f"  [FILES]      {' · '.join(parts)}")

        # Cost estimate using the same price table the meter uses.
        cost = estimate_cost_usd(
            plan.model, plan.prompt_token_estimate, completion_tokens_guess
        )
        price = PRICE_TABLE.get(plan.model)
        if price is None:
            print(f"  [COST EST]   no price entry — assumed $0")
        else:
            print(f"  [COST EST]   ~${cost:.4f}")

        # Compression status line — "fits" if the plan didn't compress.
        if plan.truncated:
            print(f"  [STATUS]     ⚠ compressed · dropped {plan.dropped_count} older turns")
        else:
            print(f"  [STATUS]     ✓ fits · no compression needed")

        # Breaker / health hint.
        if breaker_state.state == "half_open":
            print(f"  [BREAKER]    half-open (one cautious probe allowed)")
        print()

        # Soft daily cap is fine; we still want to keep iterating to show
        # what the rest of the chain would cost. But after the first healthy
        # provider we DO mark the rest as "would not be reached".
        healthy_found = True

    # Trailing context: what's the cheapest if all are healthy?
    print(_cheapest_summary(chain, history, completion_tokens_guess))


def _cheapest_summary(chain: list[str], history: list, completion_tokens_guess: int) -> str:  # type: ignore[no-untyped-def]
    """Compute the cheapest model in the chain, ignoring breaker state.

    Pure cost compare — does NOT call plan_turn (which would be expensive
    on a long history). Uses the prior plan's prompt estimate as a proxy
    by re-running plan_turn on the FIRST chain entry only and re-using
    that token count across the chain. Approximate but useful.
    """
    from app.adapters import adapter_for
    from app.workers.cost_meter import PRICE_TABLE

    out_lines = ["── Cost ranking (cheapest first) ──"]
    rows: list[tuple[str, float]] = []
    # Best-effort token count: reuse the char-estimate of history.
    chars = sum(
        sum(len(b.text) for b in m.content if hasattr(b, "text")) for m in history
    )
    prompt_est = chars // 4

    for model in chain:
        try:
            adapter_for(model)  # validate registration
        except Exception:
            continue
        price = PRICE_TABLE.get(model)
        if price is None:
            cost = 0.0
        else:
            cost = (
                prompt_est * price["prompt"]
                + completion_tokens_guess * price["completion"]
            )
        rows.append((model, cost))
    rows.sort(key=lambda x: x[1])
    for model, cost in rows:
        out_lines.append(f"  ${cost:.4f}  {model}")
    return "\n".join(out_lines)


# ── argparse / entrypoint ──────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.replay",
        description="Dump the exact request a provider would receive.",
    )
    parser.add_argument("conversation_id", type=str)
    parser.add_argument(
        "target_model",
        type=str,
        nargs="?",
        default=None,
        help=(
            "Canonical model id (e.g. gemini-2.5-flash). Required unless "
            "--dry-run is passed."
        ),
    )
    parser.add_argument(
        "--force-compression",
        action="store_true",
        help=(
            "Shrink the compression trigger ratio for this run so the "
            "six-part assembly engages even on small/synthetic chats."
        ),
    )
    parser.add_argument(
        "--show-cost",
        action="store_true",
        help=(
            "Append a cost estimate using the cost-meter price table."
        ),
    )
    parser.add_argument(
        "--completion-tokens",
        type=int,
        default=500,
        help="Assumed completion token count for the cost estimate (default 500).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Phase 6 — simulate switching to each provider in the fallback "
            "chain. Shows section sizes, file strategies, token count, and "
            "cost estimate per provider. No network calls."
        ),
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "Phase 6 — open the Jaeger search URL for this conversation_id "
            "in a browser. The URL is always printed regardless."
        ),
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

    if args.dry_run:
        asyncio.run(_dry_run(conv_id, completion_tokens_guess=args.completion_tokens))
        return

    if not args.target_model:
        parser.error("target_model is required unless --dry-run is passed")

    asyncio.run(
        _run(
            conv_id,
            args.target_model,
            show_cost=args.show_cost,
            completion_tokens_guess=args.completion_tokens,
            trace=args.trace,
        )
    )


if __name__ == "__main__":
    main()
