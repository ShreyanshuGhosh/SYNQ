import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://synq:synq_dev_password@localhost:5432/synq_dev"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_url: str = "redis://localhost:6380/0"
    # When true, Celery tasks run synchronously in-process instead of going
    # to a separate worker. Used on memory-constrained free hosting (Render
    # free tier, 512MB) where running a second worker process risks OOM.
    # Off by default so local dev keeps the real broker + worker behavior.
    celery_eager: bool = False
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "synq_minio"
    s3_secret_key: str = "synq_minio_password"
    s3_bucket: str = "synq-files"
    # S3 region used for SigV4 signing. MinIO/R2 ignore it (any value works),
    # but Supabase Storage validates it against the project's region — set
    # S3_REGION to your Supabase project region (e.g. ap-southeast-1) there.
    s3_region: str = "us-east-1"
    secret_key: str = "change-me-in-production"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Clerk
    clerk_jwks_url: str = ""  # e.g. https://your-clerk-instance.clerk.accounts.dev/.well-known/jwks.json
    clerk_issuer: str = ""  # e.g. https://your-clerk-instance.clerk.accounts.dev
    clerk_webhook_secret: str = ""  # whsec_... from Clerk dashboard

    # Provider API keys (LiteLLM picks the right one per adapter).
    # All Phase 2 providers are free-tier: signup-only, no credit card.
    gemini_api_key: str = ""
    mistral_api_key: str = ""
    groq_api_key: str = ""
    default_model: str = "gemini-2.5-flash"

    # Rate limiting
    rate_limit_per_minute: int = 60

    # File pipeline (Phase 3)
    # Hard upload ceiling enforced at the API edge before bytes hit S3.
    max_file_size_mb: int = 20
    # Documents over this token count get chunked into ~500-token chunks.
    chunk_trigger_tokens: int = 4000
    chunk_target_tokens: int = 500
    # Vision description model — kept independent of the user's currently
    # selected chat model so cost stays predictable. Free-tier Groq
    # vision-capable Llama works for OCR/captioning; swap to gpt-4o-mini
    # or claude-haiku once funded (SYNQ_STRUCT §"File Pipeline").
    description_model: str = "groq-llama-vision"
    # Gemini Files API (returned URIs are valid for 48h per Google docs).
    gemini_file_ttl_seconds: int = 47 * 60 * 60

    # ── Phase 4 — Intelligence ─────────────────────────────────────────
    # Qdrant connection. Defaults match the docker-compose service.
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_messages: str = "synq_messages"
    qdrant_collection_file_chunks: str = "synq_file_chunks"

    # Embedding model — Mistral mistral-embed is the free-tier swap for
    # OpenAI's text-embedding-3-small called out in the architecture
    # doc. 1024-dim vectors, plenty of capacity, no Anthropic/OpenAI key.
    # The literal id below is what mistralai/litellm expect on the wire.
    embedding_model: str = "mistral/mistral-embed"
    embedding_dim: int = 1024

    # Summary worker — runs on a CHEAP model (Groq Llama 3.1 8B is the
    # free equivalent of Haiku/gpt-4o-mini called out in the spec).
    # Per the Phase 4 hard constraint: hard-coded; not user-configurable.
    summary_model: str = "groq/llama-3.1-8b-instant"
    # Fact-extractor uses the same cheap model; kept as a separate knob
    # in case we want to scale it independently later.
    fact_extraction_model: str = "groq/llama-3.1-8b-instant"

    # Context engine — six-part assembly tuning knobs. The architecture
    # doc fixes these; we expose them as settings so the test fixture
    # can shrink them when validating behavior on tiny conversations.
    verbatim_window_turns: int = 15
    rag_top_k: int = 8
    summary_trigger_every_n_turns: int = 10
    # Compression kicks in when token estimate exceeds window * ratio.
    compression_trigger_ratio: float = 0.75

    # ── Phase 5 — Resilience ───────────────────────────────────────────
    # Comma-separated chain of canonical model ids (matches keys in the
    # adapter registry). Order = preference. The router walks this chain
    # on failure of the preferred model.
    fallback_chain: str = "gemini-2.5-flash,groq-llama-3.1-8b,mistral-small-latest"
    # Promote the cheapest/fastest model in the chain to first position
    # when the prompt is small (default <200 tokens). Saves quota on
    # one-liners. Toggle off if you always want the preferred model.
    cost_aware_routing: bool = True
    cost_aware_prompt_threshold: int = 200

    # Circuit breaker — Redis sliding window. Thresholds match the
    # ARCHITECTURE §"Circuit Breakers" spec.
    circuit_failure_threshold: int = 5
    circuit_window_seconds: int = 30
    circuit_degraded_ttl_seconds: int = 60

    # Health probes — Beat task interval. Spec says 30s; bumped to 5min
    # because free-tier providers have daily request caps and per-provider
    # probes would consume a meaningful chunk of quota at 30s cadence.
    health_probe_interval_seconds: int = 300
    health_state_ttl_seconds: int = 900  # 15min — covers two missed probes

    # Retry policy on 429s — exponential backoff within the same provider
    # before falling through to the next provider in the chain.
    retry_max_attempts_per_provider: int = 3
    retry_initial_backoff_seconds: float = 1.0

    # Cost meter — personal use, soft warning only.
    daily_soft_limit_usd: float = 10.0
    # HARD limit is the only thing that BLOCKS a request. Unset by default
    # (no hard limit). Set to a number to enforce. The soft limit above
    # logs a warning and shows a banner; it never refuses a request.
    hard_daily_limit_usd: float | None = None

    @field_validator("s3_endpoint", "qdrant_url", mode="before")
    @classmethod
    def _clean_endpoint(cls, v: object) -> object:
        """Drop any char that can't legally appear in a URL.

        Pasting an endpoint into a hosting dashboard can inject a
        non-breaking space, zero-width char, or BOM that stays invisible
        but makes botocore/httpx raise a confusing "Invalid endpoint".
        A real S3/Qdrant URL is pure printable ASCII, so stripping
        everything outside 0x21–0x7E is safe and bulletproof.
        """
        return re.sub(r"[^\x21-\x7e]", "", v) if isinstance(v, str) else v

    @field_validator("clerk_issuer", "clerk_jwks_url", mode="before")
    @classmethod
    def _clean_clerk_url(cls, v: object) -> object:
        """Defensively strip whitespace + trailing slash from Clerk URLs.

        Pasting these into a hosting dashboard often picks up a trailing
        newline or slash. The JWT `iss` claim has neither, so an unstripped
        value fails issuer validation with a confusing 401. Normalizing here
        makes the check robust to copy-paste artifacts.
        """
        return v.strip().rstrip("/") if isinstance(v, str) else v

    @property
    def sync_database_url(self) -> str:
        """psycopg URL for Alembic migrations (sync driver)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
            "postgresql://", "postgresql+psycopg://"
        )

    @property
    def async_database_url(self) -> str:
        """asyncpg URL for application runtime."""
        if "+asyncpg" in self.database_url:
            return self.database_url
        return self.database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://").replace(
            "postgresql://", "postgresql+asyncpg://"
        )


settings = Settings()
