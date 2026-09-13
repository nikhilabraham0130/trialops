"""Tests for application configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from trialops.core.config import LogLevel, RuntimeEnvironment, Settings


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local development settings work without environment variables."""
    monkeypatch.delenv("TRIALOPS_ENV", raising=False)
    monkeypatch.delenv("TRIALOPS_LOG_LEVEL", raising=False)
    monkeypatch.delenv("TRIALOPS_DATABASE_URL", raising=False)

    settings = Settings()

    assert settings.env is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+psycopg://trialops:trialops@localhost:5432/trialops"
    )
    assert str(settings.database_url) == "**********"


def test_settings_load_trialops_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """TRIALOPS-prefixed environment variables override defaults."""
    monkeypatch.setenv("TRIALOPS_ENV", "test")
    monkeypatch.setenv("TRIALOPS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "TRIALOPS_DATABASE_URL",
        "postgresql+psycopg://app:secret@database.example:5433/trialops_test",
    )

    settings = Settings()

    assert settings.env is RuntimeEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+psycopg://app:secret@database.example:5433/trialops_test"
    )


def test_settings_reject_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misspelled environment fails validation during startup."""
    monkeypatch.setenv("TRIALOPS_ENV", "prodution")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "database_url",
    [
        "not-a-url",
        "sqlite+aiosqlite:///trialops.db",
        "postgresql+psycopg://localhost/trialops",
        "postgresql+psycopg://trialops@/trialops",
        "postgresql+psycopg://trialops@localhost",
    ],
)
def test_settings_reject_invalid_database_urls(database_url: str) -> None:
    """Startup fails for malformed, unsupported, or incomplete database URLs."""
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr(database_url))
