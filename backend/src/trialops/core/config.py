"""Typed application settings loaded from the process environment."""

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Return one shared settings object for the current process."""
    return Settings()
