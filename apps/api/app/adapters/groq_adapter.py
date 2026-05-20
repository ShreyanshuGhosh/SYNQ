"""Groq provider adapter — free, very fast inference.

Groq runs open-weight models (Llama 3.x, Mixtral, DeepSeek-R1-Distill,
Qwen) on custom LPU hardware. Free tier with generous per-day limits.
Wire format is OpenAI Chat Completions verbatim.

Quirks handled:
  * Model ids are bare (`llama-3.1-8b-instant`, `llama-3.3-70b-versatile`)
    — no vendor prefix.
  * Strict token-per-minute rate limit on the free tier; we surface
    429s as standard provider errors (Phase 5 will add backoff).
  * `stream_options.include_usage` is honored — usage arrives in the
    final chunk, no fallback counting needed.

System messages stay as `role="system"` in the wire payload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.adapters._openai_compat import (
    count_openai_compatible,
    messages_to_openai_wire,
    stream_openai_compatible,
)
from app.adapters.base import StreamEvent, ValidationResult
from app.config import settings
from app.models import Message


class GroqAdapter:
    provider = "groq"
    # Llama 3.1 8B / 3.3 70B on Groq both expose 128k context windows
    # on the free tier (with per-request truncation at ~32k).
    context_window = 128_000

    _API_BASE = "https://api.groq.com/openai/v1"

    def __init__(self, model: str, provider_model_id: str) -> None:
        self.model = model
        self.provider_model_id = provider_model_id

    async def translate_messages(self, canonical: list[Message]) -> dict[str, Any]:
        """Canonical -> OpenAI wire (system as a message, not top-level)."""
        return {
            "model": self.provider_model_id,
            "messages": messages_to_openai_wire(canonical),
        }

    async def translate_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        # Phase 2 stub; Groq accepts OpenAI tool schema verbatim.
        if not tools:
            return {}
        return {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {}),
                    },
                }
                for t in tools
            ]
        }

    async def count_tokens(self, messages: list[Message]) -> int:
        return count_openai_compatible(f"groq/{self.provider_model_id}", messages)

    async def stream_completion(
        self, request: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        # LiteLLM uses the model-id prefix to pick its dialect.
        return stream_openai_compatible(
            provider_model_id=f"groq/{self.provider_model_id}",
            messages=request.get("messages", []),
            api_key=settings.groq_api_key or None,
            api_base=self._API_BASE,
        )

    async def validate(self, request: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        msgs = request.get("messages", [])
        if not msgs:
            errors.append("groq: empty messages array")
        # Groq rejects empty `content` strings on user messages.
        for i, m in enumerate(msgs):
            if m.get("role") == "user" and not (m.get("content") or "").strip():
                errors.append(f"groq: empty user content at index {i}")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)
