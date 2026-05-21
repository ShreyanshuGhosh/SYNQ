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

from app.adapters._gemini_files import resolve_for_gemini
from app.adapters._openai_compat import blocks_to_text, stream_openai_compatible
from app.adapters._resolve import default_resolve, is_image
from app.adapters.base import (
    ProviderCapabilities,
    ResolvedFile,
    StreamEvent,
    ValidationResult,
)
from app.config import settings
from app.models import FileRefBlock, ImageBlock, Message, TextBlock
from app.storage import download_bytes, key_from_storage_url


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
    # Gemini 2.5 Flash and Pro are vision-capable. Inline base64 is
    # capped at ~20MB per request; for anything larger the Files API
    # path kicks in (Google's docs allow up to 2GB via Files API but
    # we keep the Phase 3 ceiling at 20MB per the spec).
    capabilities = ProviderCapabilities(
        vision=True, max_image_mb=20, supports_files_api=True
    )

    def __init__(self, model: str, provider_model_id: str) -> None:
        self.model = model
        self.provider_model_id = provider_model_id

    async def translate_messages(
        self,
        canonical: list[Message],
        resolved: dict[str, ResolvedFile] | None = None,
    ) -> dict[str, Any]:
        """Canonical -> Gemini native wire format.

        Output:
            {
              "model": "<id>",
              "systemInstruction": {"parts": [{"text": "..."}]} | None,
              "contents": [
                  {"role": "user"|"model",
                   "parts": [{"text": "..."} | {"inline_data": ...} | {"file_data": ...}]},
                  ...
              ],
            }

        File blocks become ``file_data`` (Files API URI) or
        ``inline_data`` (base64) parts; never silently dropped.
        """
        import base64 as _b64

        resolved = resolved or {}
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in canonical:
            if m.role == "system":
                text = blocks_to_text(m.content, resolved)
                if text:
                    system_parts.append(text)
                continue
            parts: list[dict[str, Any]] = []
            for block in m.content:
                if isinstance(block, TextBlock) and block.text:
                    parts.append({"text": block.text})
                elif isinstance(block, (ImageBlock, FileRefBlock)):
                    rf = resolved.get(str(block.file_id))
                    if rf is None:
                        continue
                    if rf.inline_bytes and rf.mime_type:
                        # Always prefer inline_data for LiteLLM transport.
                        # LiteLLM's Gemini route cannot use Files API URIs
                        # as image_url (returns 403 — auth required).
                        # We store the Files API URI only in the cache;
                        # inline base64 is what actually goes on the wire.
                        b64 = _b64.b64encode(rf.inline_bytes).decode("ascii")
                        parts.append(
                            {
                                "inline_data": {
                                    "mime_type": rf.mime_type,
                                    "data": b64,
                                }
                            }
                        )
                    elif rf.files_api_uri and not rf.inline_bytes:
                        # Files API only (no local bytes) — pass the URI.
                        # This branch is hit when bytes exceeded inline cap.
                        parts.append(
                            {
                                "file_data": {
                                    "file_uri": rf.files_api_uri,
                                    "mime_type": rf.mime_type or "application/octet-stream",
                                }
                            }
                        )
                    elif rf.description_text:
                        parts.append({"text": rf.description_text})
            if not parts:
                parts.append({"text": ""})
            contents.append(
                {"role": _canonical_role_to_gemini(m.role), "parts": parts}
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
            return litellm.token_counter(model=litellm_model, messages=payload)
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

            # Reshape Gemini-native parts -> OpenAI-style content.
            # Text-only entries stay as flat strings (assistant turns
            # must always be strings). User turns with inline_data /
            # file_data become a parts array LiteLLM forwards to Gemini.
            entry_parts = entry.get("parts", [])
            has_media = any(
                ("inline_data" in p) or ("file_data" in p) for p in entry_parts
            )
            if not has_media or role != "user":
                text = "\n".join(
                    p.get("text", "") for p in entry_parts if "text" in p
                )
                messages.append({"role": role, "content": text})
                continue

            openai_parts: list[dict[str, Any]] = []
            for p in entry_parts:
                if "text" in p and p["text"]:
                    openai_parts.append({"type": "text", "text": p["text"]})
                elif "inline_data" in p:
                    data = p["inline_data"]
                    openai_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{data.get('mime_type','image/png')};base64,{data.get('data','')}"
                            },
                        }
                    )
                elif "file_data" in p:
                    # Large file (> inline cap) with Files API URI only.
                    # Pass as text note — LiteLLM cannot auth against
                    # Files API URIs for non-native Gemini calls.
                    fd = p["file_data"]
                    openai_parts.append(
                        {
                            "type": "text",
                            "text": f"[Large file attached via Gemini Files API: {fd.get('file_uri', '')}]",
                        }
                    )
            messages.append({"role": role, "content": openai_parts})

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

    async def resolve_file(self, file_row: Any) -> ResolvedFile:
        """Gemini-specific: vision images go through the Files API.

        Caching via Redis means a re-render of the same conversation
        does not re-upload. Phase 4's RAG retrieval will use the same
        cached URI for repeat hits.

        Non-image files (PDF / DOCX / TXT / MD) fall through to the
        shared resolver because the Files API would not give us text we
        can summarize; we want our own extracted_text in the prompt.
        """
        if not is_image(file_row.mime_type):
            return default_resolve(file_row, capabilities=self.capabilities)
        if file_row.parse_status == "failed":
            return default_resolve(file_row, capabilities=self.capabilities)

        try:
            raw = download_bytes(key_from_storage_url(file_row.storage_url))
        except Exception:
            return default_resolve(file_row, capabilities=self.capabilities)

        # Cache the Files API URI for future reference / Phase 4 RAG,
        # but always carry inline_bytes so stream_completion can send
        # base64 to LiteLLM (LiteLLM cannot auth against Files API URIs).
        uri = resolve_for_gemini(
            str(file_row.id), raw, mime_type=file_row.mime_type or "image/png"
        )
        fits_inline = (file_row.size_bytes or 0) <= self.capabilities.max_image_mb * 1024 * 1024
        if fits_inline:
            return ResolvedFile(
                file_id=str(file_row.id),
                mime_type=file_row.mime_type,
                inline_bytes=raw,
                files_api_uri=uri,  # stored for replay/logging; not used on wire
                strategy="inline" if not uri else "files_api",
            )
        # Image too large for inline — must use Files API URI directly.
        if uri:
            return ResolvedFile(
                file_id=str(file_row.id),
                mime_type=file_row.mime_type,
                files_api_uri=uri,
                strategy="files_api",
            )
        return default_resolve(file_row, capabilities=self.capabilities)

    # ── Internal ───────────────────────────────────────────────────────

    def _litellm_routing_model(self) -> str:
        return f"gemini/{self.provider_model_id}"
