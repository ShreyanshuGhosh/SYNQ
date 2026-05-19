"""LiteLLM streaming wrapper.

Phase 1 is Gemini-only (free tier for development). The single entry point is
`stream_completion(...)` which yields `StreamEvent`s — the canonical event
shape from SYNQ_STRUCT.pdf §"Stream Event Normalization". Phase 2 swaps
providers behind the same surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import litellm

from app.config import settings
from app.models import ContentBlock, Message, TextBlock

# Canonical model name → LiteLLM routing string. Pinned versions — never
# "latest" (see PDF "Provider Drift"). Anything containing "/" already has a
# provider prefix and is passed through as-is.
_MODEL_TO_LITELLM: dict[str, str] = {
    "gemini-2.5-flash": "gemini/gemini-2.5-flash",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "gemini-2.0-flash": "gemini/gemini-2.0-flash",
    "gemini-2.0-flash-lite": "gemini/gemini-2.0-flash-lite",
}

StreamEventType = Literal["text", "tool_use", "tool_use_delta", "stop", "error"]


@dataclass
class StreamEvent:
    type: StreamEventType
    content: str | dict[str, Any] | None = None
    usage: dict[str, int] | None = None  # final event includes token counts


def _provider_for(model: str) -> str:
    """Return the canonical provider id for a model (the LiteLLM prefix).

    Used as the JSONB key under `messages.token_counts` per the canonical
    data model: {"gemini": 142}, not a bare integer.
    """
    resolved = _resolve_model(model)
    return resolved.split("/", 1)[0] if "/" in resolved else "gemini"


def _resolve_model(model: str) -> str:
    if "/" in model:
        return model
    return _MODEL_TO_LITELLM.get(model, f"gemini/{model}")


def _content_blocks_to_litellm(blocks: list[ContentBlock]) -> str:
    """Phase 1 only supports text blocks. Concatenate the text payload.

    Later phases will translate multimodal blocks (image/file_ref) per provider.
    """
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        # Non-text blocks are ignored in Phase 1 — Phase 3 wires them in.
    return "\n".join(parts)


def messages_to_litellm(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        out.append({"role": m.role, "content": _content_blocks_to_litellm(m.content)})
    return out


async def stream_completion(
    messages: list[Message],
    model: str = "",
) -> AsyncIterator[StreamEvent]:
    """Stream a completion from Gemini via LiteLLM.

    Yields canonical StreamEvents. The terminal event is always `stop` (with
    `usage` populated) or `error`.
    """
    model_name = model or settings.default_model
    litellm_model = _resolve_model(model_name)
    payload = messages_to_litellm(messages)

    try:
        response = await litellm.acompletion(
            model=litellm_model,
            messages=payload,
            stream=True,
            api_key=settings.gemini_api_key or None,
            # Tells LiteLLM to emit a final chunk with usage populated. Without
            # this, providers (including Gemini) stream pure deltas and
            # token_counts ends up NULL in the DB.
            stream_options={"include_usage": True},
        )
    except Exception as exc:
        yield StreamEvent(type="error", content=str(exc))
        return

    usage: dict[str, int] | None = None
    accumulated: list[str] = []
    try:
        async for chunk in response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                pt = getattr(chunk_usage, "prompt_tokens", 0) or 0
                ct = getattr(chunk_usage, "completion_tokens", 0) or 0
                tt = getattr(chunk_usage, "total_tokens", 0) or 0
                if tt or pt or ct:
                    usage = {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt or (pt + ct),
                    }
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            text_piece = getattr(delta, "content", None)
            if text_piece:
                accumulated.append(text_piece)
                yield StreamEvent(type="text", content=text_piece)
    except Exception as exc:
        yield StreamEvent(type="error", content=str(exc))
        return

    # LiteLLM's `include_usage` does not surface a usage chunk reliably for
    # every provider (notably Gemini streaming). Fall back to per-model
    # token counting on the prompt + assistant output so token_counts is
    # always populated.
    if usage is None:
        try:
            prompt_tokens = litellm.token_counter(
                model=litellm_model, messages=payload
            )
            completion_tokens = litellm.token_counter(
                model=litellm_model, text="".join(accumulated)
            )
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        except Exception:
            usage = None

    yield StreamEvent(type="stop", usage=usage)


def token_counts_from_usage(model: str, usage: dict[str, int] | None) -> dict[str, int] | None:
    """Build the JSONB token_counts map keyed by provider id."""
    if usage is None:
        return None
    provider = _provider_for(model)
    return {provider: usage.get("total_tokens") or 0}
