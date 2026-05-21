"""Image description generation — synchronous, called from Celery.

CRITICAL constraint from Phase 3 spec: description generation uses a
SEPARATE CHEAP model call, NOT the user's currently selected provider.
This decouples file-prep cost from chat cost — uploading a 50-page PDF
to a Mistral conversation must not bill the user for Mistral OCR
descriptions of every embedded image.

For the free-tier project we use Groq's vision-capable Llama 3.2 11B
endpoint. When budget exists, swap ``settings.description_model`` to
``gpt-4o-mini`` or ``claude-haiku`` — the only place that name is read
is here.

Errors are non-fatal: a missing description still leaves OCR text from
tesseract available, so the parse pipeline keeps going.
"""

from __future__ import annotations

import base64
import logging

import litellm

from app.config import settings

logger = logging.getLogger(__name__)


_DESCRIBE_PROMPT = (
    "Describe this image in detail. Identify objects, text, layout, and "
    "any contextual information another model would need to reason about "
    "this image without seeing it. Be specific. No preamble."
)


# Groq's vision endpoints accept OpenAI's multimodal message shape.
# Default model id is documented on console.groq.com — pinning to a
# concrete id (not "latest") follows SYNQ_STRUCT §"Provider Drift".
_DESCRIPTION_MODELS: dict[str, str] = {
    "groq-llama-vision": "groq/meta-llama/llama-4-scout-17b-16e-instruct",
    "gpt-4o-mini": "gpt-4o-mini",
    "claude-haiku": "claude-haiku-4-5-20251001",
}


def describe_image(image_bytes: bytes, mime_type: str) -> str | None:
    """Return a textual description of `image_bytes`. None on failure."""
    if not image_bytes:
        return None
    model_id = _DESCRIPTION_MODELS.get(
        settings.description_model, settings.description_model
    )
    api_key = settings.groq_api_key or None
    data_url = f"data:{mime_type or 'image/png'};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    try:
        resp = litellm.completion(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _DESCRIBE_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            api_key=api_key,
            api_base="https://api.groq.com/openai/v1"
            if settings.description_model == "groq-llama-vision"
            else None,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        logger.exception("describe_image: vision call failed (model=%s)", model_id)
        return None
