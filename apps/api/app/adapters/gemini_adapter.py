"""Gemini provider adapter.

Quirks (per SYNQ_STRUCT §"Per-Provider Quirks"):
  * Assistant role is "model" (not "assistant").
  * Messages live under `contents`, each with a `parts` array of typed
    blocks ({text: ...}, {inline_data: ...}, etc.) — not a plain string.
  * `systemInstruction` is a top-level field, not a message.
  * Tools use `function_declarations` (not `tools`).

`translate_messages` returns Gemini's NATIVE wire shape so the replay
tool shows exactly what the provider would see. At stream time we
reshape that back into the OpenAI-style call LiteLLM expects, because
LiteLLM is what actually drives the HTTP transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from app.adapters._openai_compat import blocks_to_text, stream_openai_compatible
from app.adapters.base import StreamEvent, ValidationResult
from app.config import settings
from app.models import Message


def _canonical_role_to_gemini(role: str) -> str:
    # The single most-tripped-over Gemini quirk: assistant -> model.
    if role == "assistant":
        return "model"
    if role == "system":
        # Caller pulls these out into systemInstruction; if anything
        # still slips through we map to "user" rather than emit an
        # invalid role.
        return "user"
    return role  # "user"


class GeminiAdapter:
    provider = "gemini"
    # 1M tokens on 2.5 Pro/Flash. Single conservative value for Phase 2.
    context_window = 1_000_000

    def __init__(self, model: str, provider_model_id: str) -> None:
        self.model = model
        self.provider_model_id = provider_model_id

    async def translate_messages(self, canonical: list[Message]) -> dict[str, Any]:
        """Canonical -> Gemini native wire format.

        Output:
            {
              "model": "<id>",
              "systemInstruction": {"parts": [{"text": "..."}]} | None,
              "contents": [
                  {"role": "user"|"model", "parts": [{"text": "..."}]},
                  ...
              ],
            }
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in canonical:
            text = blocks_to_text(m.content)
            if m.role == "system":
                if text:
                    system_parts.append(text)
                continue
            contents.append(
                {
                    "role": _canonical_role_to_gemini(m.role),
                    "parts": [{"text": text}],
                }
            )

        out: dict[str, Any] = {
            "model": self.provider_model_id,
            "contents": contents,
        }
        if system_parts:
            out["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }
        return out

    async def translate_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        # Phase 2 stub. Gemini shape when wired later:
        #   {"tools": [{"function_declarations": [{"name":..., "parameters":{...}}]}]}
        if not tools:
            return {}
        return {
            "tools": [
                {
                    "function_declarations": [
                        {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {}),
                        }
                        for t in tools
                    ]
                }
            ]
        }

    async def count_tokens(self, messages: list[Message]) -> int:
        """LiteLLM routes to Gemini's count_tokens endpoint for the
        `gemini/...` model id."""
        payload = [
            {"role": m.role, "content": blocks_to_text(m.content)} for m in messages
        ]
        litellm_model = self._litellm_routing_model()
        try:
            return int(litellm.token_counter(model=litellm_model, messages=payload))
        except Exception:
            return sum(len(p["content"]) for p in payload) // 4

    async def stream_completion(
        self, request: dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """Reshape Gemini-native -> OpenAI-style for LiteLLM transport.

        LiteLLM's Gemini route translates internally; we feed it the
        flattened OpenAI shape it expects.
        """
        messages: list[dict[str, Any]] = []
        if (si := request.get("systemInstruction")) is not None:
            text = "\n\n".join(p.get("text", "") for p in si.get("parts", []))
            if text:
                messages.append({"role": "system", "content": text})

        for entry in request.get("contents", []):
            role = entry["role"]
            if role == "model":
                role = "assistant"  # back to canonical for LiteLLM
            text = "\n".join(
                part.get("text", "") for part in entry.get("parts", []) if "text" in part
            )
            messages.append({"role": role, "content": text})

        return stream_openai_compatible(
            provider_model_id=self._litellm_routing_model(),
            messages=messages,
            api_key=settings.gemini_api_key or None,
        )

    async def validate(self, request: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        contents = request.get("contents", [])
        if not contents:
            errors.append("gemini: empty contents array")
        for i, entry in enumerate(contents):
            if entry.get("role") not in ("user", "model"):
                errors.append(
                    f"gemini: invalid role {entry.get('role')!r} at index {i}"
                )
            parts = entry.get("parts", [])
            if not parts:
                errors.append(f"gemini: empty parts at index {i}")
        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    # ── Internal ───────────────────────────────────────────────────────

    def _litellm_routing_model(self) -> str:
        return f"gemini/{self.provider_model_id}"
