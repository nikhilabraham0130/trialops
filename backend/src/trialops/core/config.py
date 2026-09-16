"""Typed application settings loaded from the process environment."""

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://trialops:change-me-for-local-development@127.0.0.1:55432/trialops"
)


class RuntimeEnvironment(StrEnum):
    """Environments in which the TrialOps API may run."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Validated, immutable settings for one application process."""

    model_config = SettingsConfigDict(
        env_prefix="TRIALOPS_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    env: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Require the PostgreSQL driver and connection details used by TrialOps."""
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError):
            raise ValueError("database URL is not a valid SQLAlchemy URL") from None

        if url.drivername != "postgresql+psycopg":
            raise ValueError("database URL must use the postgresql+psycopg driver")

        missing_parts = [
            name
            for name, part in (
                ("username", url.username),
                ("host", url.host),
                ("database name", url.database),
            )
            if not part
        ]
        if missing_parts:
            missing = ", ".join(missing_parts)
            raise ValueError(f"database URL is missing: {missing}")

        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require explicit browser origins rather than unrestricted access."""
        if not value:
            raise ValueError("at least one CORS origin is required")
        if "*" in value:
            raise ValueError("wildcard CORS origins are not permitted")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one shared settings object for the current process."""
    return Settings()
