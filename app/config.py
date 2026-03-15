from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_BASE_URL: str = "http://localhost:8000"
    MCP_BASE_URL: str = "http://localhost:8000"
    AUTH_BASE_URL: str = "http://localhost:8000"

    YANDEX_CLIENT_ID: str = Field(default="")
    YANDEX_CLIENT_SECRET: str = Field(default="")
    YANDEX_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    YANDEX_ORG_ID: str = Field(default="")

    POSTGRES_DSN: str = "postgresql+asyncpg://wiki:wiki@localhost:5432/wiki"
    REDIS_DSN: str = "redis://localhost:6379/0"

    TOKEN_ENCRYPTION_KEY: str = Field(default="")

    AUTH_SESSION_TTL_SECONDS: int = 900
    PAGE_CACHE_TTL_SECONDS: int = 300
    ACCESS_TOKEN_REFRESH_SKEW_SECONDS: int = 60

    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
