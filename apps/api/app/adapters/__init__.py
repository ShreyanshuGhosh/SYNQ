"""Adapter registry.

The orchestrator looks up an adapter by model name and gets back a
ProviderAdapter. It never branches on provider id.

Model -> adapter mapping is the ONLY place that knows which model belongs
to which provider. Adding a new provider means: implement the protocol,
register it here. Nothing else changes.

Phase 2 providers — all free:
  * Gemini  — Google free tier (carries over from Phase 1)
  * Mistral — la Plateforme free "Experiment" tier (own quota pool)
  * Groq    — fast free inference on Llama / Gemma
"""

from __future__ import annotations

from app.adapters.base import (
    ProviderAdapter,
    StreamEvent,
    StreamEventType,
    TranslationRequest,
    ValidationResult,
)
from app.adapters.gemini_adapter import GeminiAdapter
from app.adapters.groq_adapter import GroqAdapter
from app.adapters.mistral_adapter import MistralAdapter

__all__ = [
    "ProviderAdapter",
    "StreamEvent",
    "StreamEventType",
    "TranslationRequest",
    "ValidationResult",
    "adapter_for",
    "list_models",
    "provider_for",
]


# Each model name maps to (adapter_class, provider_model_id). The
# `provider_model_id` is the literal string the provider expects on the
# wire (already version-pinned per "Provider Drift" — never "latest").
_MODEL_TABLE: dict[str, tuple[type, str]] = {
    # Gemini (Phase 1 default — keep).
    "gemini-2.5-flash": (GeminiAdapter, "gemini-2.5-flash"),
    # "gemini-2.5-pro": (GeminiAdapter, "gemini-2.5-pro"),
    # "gemini-2.0-flash": (GeminiAdapter, "gemini-2.0-flash"),
    # "gemini-2.0-flash-lite": (GeminiAdapter, "gemini-2.0-flash-lite"),
    # Mistral — la Plateforme free "Experiment" tier. Bare model ids on
    # api.mistral.ai. Free tier has its own quota pool so these stay
    # reliably available (unlike OpenRouter's shared free pool).
    "mistral-small-latest": (MistralAdapter, "mistral-small-latest"),
    # "mistral-medium-latest": (MistralAdapter, "mistral-medium-latest"),
    # "open-mistral-nemo": (MistralAdapter, "open-mistral-nemo"),
    # Groq — bare model ids on Groq's OpenAI-compatible endpoint.
    "groq-llama-3.1-8b": (GroqAdapter, "llama-3.1-8b-instant"),
    # "groq-llama-3.3-70b": (GroqAdapter, "llama-3.3-70b-versatile"),
    # "groq-gemma2-9b": (GroqAdapter, "gemma2-9b-it"),
}


def adapter_for(model: str) -> ProviderAdapter:
    """Return a ProviderAdapter instance for the given canonical model id.

    Falls back to a Gemini adapter for unknown models — the Phase 1
    default. The orchestrator must not branch on this; if the model is
    unknown, the adapter's own validate() will surface the issue.
    """
    entry = _MODEL_TABLE.get(model)
    if entry is None:
        return GeminiAdapter(model=model, provider_model_id=model)
    cls, provider_model_id = entry
    return cls(model=model, provider_model_id=provider_model_id)


def provider_for(model: str) -> str:
    """Provider id used as the JSONB key in messages.token_counts."""
    return adapter_for(model).provider


def list_models() -> list[dict[str, str]]:
    """All registered models as [{id, provider}] for the picker UI."""
    out: list[dict[str, str]] = []
    for model_id, (cls, _) in _MODEL_TABLE.items():
        out.append({"id": model_id, "provider": cls.provider})
    return out
