"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from trialops.core.config import LogLevel, RuntimeEnvironment, Settings


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local development settings work without environment variables."""
    monkeypatch.delenv("TRIALOPS_ENV", raising=False)
    monkeypatch.delenv("TRIALOPS_LOG_LEVEL", raising=False)

    settings = Settings()

    assert settings.env is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO


def test_settings_load_trialops_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """TRIALOPS-prefixed environment variables override defaults."""
    monkeypatch.setenv("TRIALOPS_ENV", "test")
    monkeypatch.setenv("TRIALOPS_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.env is RuntimeEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG


def test_settings_reject_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misspelled environment fails validation during startup."""
    monkeypatch.setenv("TRIALOPS_ENV", "prodution")

    with pytest.raises(ValidationError):
        Settings()
