from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "CrimeScene AI"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg2://crimescene:crimescene@localhost:5432/crimescene"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = ""  # endpoint used in pre-signed URLs handed to browsers; defaults to s3_endpoint_url
    s3_bucket: str = "crimescene"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    presign_expiry_seconds: int = 900  # 15 minutes (Section 7.3)

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_hours: int = 12
    app_encryption_key: str = "0" * 64  # 32-byte hex key for AES-GCM of TOTP secrets

    anthropic_api_key: str = ""
    narrative_model: str = "claude-fable-5"
    qa_model: str = "claude-fable-5"
    summary_model: str = "claude-haiku-4-5-20251001"

    pipeline_fake: bool = False  # Phase 3 fake detector (env PIPELINE_FAKE=1)
    llm_fake: bool = False       # deterministic canned LLM for CI (env LLM_FAKE=1)

    # No-Redis / no-broker local runner (deploy/run_local.py):
    progress_backend: str = "redis"  # "redis" | "file"
    progress_dir: str = ".progress"
    celery_eager: bool = False       # run pipeline tasks synchronously, no worker/broker needed
    frontend_dist_dir: str = ""      # if set and exists, FastAPI serves the built SPA from here

    retention_days: int = 365

    max_upload_bytes: int = 4 * 1024**3
    max_video_seconds: int = 60 * 60
    max_media_per_case: int = 20
    max_tracked_persons: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
