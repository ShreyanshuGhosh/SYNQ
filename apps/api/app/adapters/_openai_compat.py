"""Shared helpers for OpenAI-wire-format providers (OpenRouter, Groq).

OpenRouter and Groq both speak the OpenAI Chat Completions wire format,
so 90% of their adapters is identical. The differences (base URL,
auth header, model id prefix, optional referer headers) live in the
adapter classes themselves; the message reshaping and the streaming
event normalization live here.

Important: this file is the only place that touches LiteLLM directly
for the OpenAI-shape providers. Adapters import from here, never from
litellm directly, so the import surface stays small and replaceable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from app.adapters.base import StreamEvent
from app.models import ContentBlock, Message, TextBlock


def blocks_to_text(blocks: list[ContentBlock]) -> str:
    """Phase 2 text-only flattening. Multimodal blocks land in Phase 3."""
    out: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            out.append(block.text)
    return "\n".join(out)


def messages_to_openai_wire(messages: list[Message]) -> list[dict[str, Any]]:
    """Canonical -> [{"role": ..., "content": "..."}]. System turns stay
    as role="system" (the OpenAI wire convention)."""
    return [{"role": m.role, "content": blocks_to_text(m.content)} for m in messages]


async def stream_openai_compatible(
    *,
    provider_model_id: str,
    messages: list[dict[str, Any]],
    api_key: str | None,
    api_base: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream completions from any OpenAI-compatible endpoint via LiteLLM.

    Yields canonical StreamEvents — the adapter never sees a LiteLLM
    object. The terminal event is always `stop` (with usage) or `error`.
    """
    kwargs: dict[str, Any] = {
        "model": provider_model_id,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as exc:
        yield StreamEvent(type="error", content=str(exc))
        return

    usage: dict[str, int] | None = None
    accumulated: list[str] = []
    try:
        async for chunk in response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                pt = int(getattr(chunk_usage, "prompt_tokens", 0) or 0)
                ct = int(getattr(chunk_usage, "completion_tokens", 0) or 0)
                tt = int(getattr(chunk_usage, "total_tokens", 0) or 0) or (pt + ct)
                if pt or ct or tt:
                    usage = {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": tt,
                    }
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                accumulated.append(piece)
                yield StreamEvent(type="text", content=piece)
    except Exception as exc:
        yield StreamEvent(type="error", content=str(exc))
        return

    if usage is None:
        try:
            pt = int(litellm.token_counter(model=provider_model_id, messages=messages))
            ct = int(
                litellm.token_counter(
                    model=provider_model_id, text="".join(accumulated)
                )
            )
            usage = {
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": pt + ct,
            }
        except Exception:
            usage = None

    yield StreamEvent(type="stop", usage=usage)


def count_openai_compatible(
    provider_model_id: str, messages: list[Message]
) -> int:
    """Local-ish token counter via LiteLLM (tiktoken under the hood for
    most OpenAI-wire models; heuristic fallback otherwise)."""
    payload = messages_to_openai_wire(messages)
    try:
        return int(litellm.token_counter(model=provider_model_id, messages=payload))
    except Exception:
        return sum(len(p["content"]) for p in payload) // 4
