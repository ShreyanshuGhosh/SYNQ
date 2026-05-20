from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://synq:synq_dev_password@localhost:5432/synq_dev"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_url: str = "redis://localhost:6380/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "synq_minio"
    s3_secret_key: str = "synq_minio_password"
    s3_bucket: str = "synq-files"
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
