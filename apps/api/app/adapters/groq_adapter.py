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
    messages_to_openai_vision_wire,
    messages_to_openai_wire,
    stream_openai_compatible,
)
from app.adapters._resolve import default_resolve
from app.adapters.base import (
    ProviderCapabilities,
    ResolvedFile,
    StreamEvent,
    ValidationResult,
)
from app.config import settings
from app.models import Message


# Vision flag flips per model: llama-3.1-8b-instant is text-only;
# llama-4-scout-17b-16e-instruct supports image input. Per-model
# capabilities are kept here rather than in the registry because the
# adapter knows its own model_id.
_VISION_MODELS = {
    "meta-llama/llama-4-scout-17b-16e-instruct",
}


class GroqAdapter:
    provider = "groq"
    # Llama 3.1 8B / 3.3 70B on Groq both expose 128k context windows
    # on the free tier (with per-request truncation at ~32k).
    context_window = 128_000

    _API_BASE = "https://api.groq.com/openai/v1"

    def __init__(self, model: str, provider_model_id: str) -> None:
        self.model = model
        self.provider_model_id = provider_model_id
        if provider_model_id in _VISION_MODELS:
            # Groq accepts inline base64 up to ~20MB via the OpenAI-style
            # `image_url: {url: data:...}` block.
            self.capabilities = ProviderCapabilities(vision=True, max_image_mb=20)
        else:
            self.capabilities = ProviderCapabilities(vision=False, max_image_mb=0)

    async def translate_messages(
        self,
        canonical: list[Message],
        resolved: dict[str, ResolvedFile] | None = None,
    ) -> dict[str, Any]:
        """Canonical -> OpenAI wire (system as a message, not top-level).

        Vision-capable Groq models (llama-4-scout) receive multimodal
        parts arrays on user messages; text-only models stay on the
        plain-content path.
        """
        if self.capabilities.vision and resolved:
            return {
                "model": self.provider_model_id,
                "messages": messages_to_openai_vision_wire(canonical, resolved),
            }
        return {
            "model": self.provider_model_id,
            "messages": messages_to_openai_wire(canonical, resolved),
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
            if m.get("role") == "user":
                content = m.get("content")
                # Vision messages have `content` as a list of parts; only
                # plain-string user messages are required to be non-empty.
                if isinstance(content, str) and not content.strip():
                    errors.append(f"groq: empty user content at index {i}")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    async def resolve_file(self, file_row: Any) -> ResolvedFile:
        return default_resolve(file_row, capabilities=self.capabilities)
