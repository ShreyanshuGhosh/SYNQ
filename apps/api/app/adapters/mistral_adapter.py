"""Mistral provider adapter — free tier via la Plateforme.

Mistral runs their own models (Mistral Small/Medium/Large, Codestral,
etc.) behind an OpenAI-compatible endpoint at `api.mistral.ai`. The
"Experiment" tier on console.mistral.ai is free with a generous per-day
quota (1 RPS, 500K tokens/min, 1B tokens/month at time of writing) and
does NOT share quota with other users — unlike OpenRouter's free pool,
this stays consistently available.

Quirks (per SYNQ_STRUCT §"Per-Provider Quirks" pattern):
  * Bare model ids (`mistral-small-latest`, `open-mistral-7b`) — no
    vendor prefix on the wire.
  * Strict alternation expected, like Anthropic. We rely on the
    canonical history already being alternating.
  * System messages stay as role="system" (OpenAI-wire convention).
  * `stream_options.include_usage` is honored — final chunk carries
    token counts.

LiteLLM routes through the `mistral/` prefix; we attach it only at the
transport boundary so the wire payload (and replay-tool output) shows
the bare provider model id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.adapters._openai_compat import (
    count_openai_compatible,
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


class MistralAdapter:
    provider = "mistral"
    # Mistral Small 3.x ships a 32k context window; Large is 128k. Use
    # the smaller default — Phase 4 will key this per model.
    context_window = 32_000
    # The free-tier `mistral-small-latest` is text-only. `pixtral-12b` is
    # multimodal but lives on a paid plan; we keep capabilities at the
    # safe text-only default and let the resolver substitute descriptions.
    capabilities = ProviderCapabilities(vision=False, max_image_mb=0)

    _API_BASE = "https://api.mistral.ai/v1"

    def __init__(self, model: str, provider_model_id: str) -> None:
        self.model = model
        self.provider_model_id = provider_model_id

    async def translate_messages(
        self,
        canonical: list[Message],
        resolved: dict[str, ResolvedFile] | None = None,
    ) -> dict[str, Any]:
        """Canonical -> OpenAI wire (system stays as role='system').

        Mistral free-tier is text-only, so file blocks become
        description text via the resolved-files map.
        """
        return {
            "model": self.provider_model_id,
            "messages": messages_to_openai_wire(canonical, resolved),
        }

    async def translate_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        # Phase 2 stub. Mistral accepts OpenAI tool schema verbatim.
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
        return count_openai_compatible(
            f"mistral/{self.provider_model_id}", messages
        )

    async def stream_completion(
        self, request: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        # LiteLLM uses the model-id prefix to pick its dialect.
        return stream_openai_compatible(
            provider_model_id=f"mistral/{self.provider_model_id}",
            messages=request.get("messages", []),
            api_key=settings.mistral_api_key or None,
            api_base=self._API_BASE,
        )

    async def validate(self, request: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        msgs = request.get("messages", [])
        if not msgs:
            errors.append("mistral: empty messages array")
        # Mistral rejects empty content on user/assistant turns.
        for i, m in enumerate(msgs):
            if m.get("role") in ("user", "assistant") and not (
                m.get("content") or ""
            ).strip():
                errors.append(f"mistral: empty {m['role']} content at index {i}")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    async def resolve_file(self, file_row: Any) -> ResolvedFile:
        # Text-only on the free tier: always substitute description /
        # extracted text. The shared resolver handles every case.
        return default_resolve(file_row, capabilities=self.capabilities)
