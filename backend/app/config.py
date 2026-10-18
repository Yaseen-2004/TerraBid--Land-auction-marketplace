from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env files."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TerraBid Land Auctions"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/landauction"
    db_pool_size: int = Field(default=20, ge=1)
    db_max_overflow: int = Field(default=30, ge=0)
    db_pool_timeout: int = Field(default=30, ge=1)

    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=500, ge=10)

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "terrabid"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=60 * 24 * 7)

    esri_api_key: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]

    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_bids_per_10s: int = 20
    rate_limit_writes_per_minute: int = 60

    run_background_tasks: bool = True
    lifecycle_interval_seconds: float = Field(default=1.0, gt=0)
    reconcile_interval_seconds: float = Field(default=5.0, gt=0)
    stream_reconcile_age_ms: int = Field(default=5000, ge=0)
    ended_state_ttl_seconds: int = Field(default=86400, ge=60)

    ws_allow_anonymous: bool = True
    ws_heartbeat_seconds: int = Field(default=25, ge=5)
    ws_send_queue_size: int = Field(default=256, ge=8)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _force_async_driver(cls, value: str) -> str:
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix):]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
