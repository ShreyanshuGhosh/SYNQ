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


settings = Settings()
