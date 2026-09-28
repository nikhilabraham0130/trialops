"""Tests for application configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from trialops.core.config import LLMProvider, LogLevel, RuntimeEnvironment, Settings


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local development settings work without environment variables."""
    monkeypatch.delenv("TRIALOPS_ENV", raising=False)
    monkeypatch.delenv("TRIALOPS_LOG_LEVEL", raising=False)
    monkeypatch.delenv("TRIALOPS_DATABASE_URL", raising=False)
    monkeypatch.delenv("TRIALOPS_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("TRIALOPS_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRIALOPS_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("TRIALOPS_LLM_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    settings = Settings()

    assert settings.env is RuntimeEnvironment.DEVELOPMENT
    assert settings.log_level is LogLevel.INFO
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+psycopg://trialops:change-me-for-local-development@127.0.0.1:55432/trialops"
    )
    assert str(settings.database_url) == "**********"
    assert settings.cors_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    assert settings.llm_provider is LLMProvider.DEEPSEEK
    assert settings.llm_api_key is None
    assert str(settings.llm_base_url) == "https://api.deepseek.com/"
    assert settings.llm_model == "deepseek-flash"


def test_settings_load_trialops_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """TRIALOPS-prefixed environment variables override defaults."""
    monkeypatch.setenv("TRIALOPS_ENV", "test")
    monkeypatch.setenv("TRIALOPS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "TRIALOPS_DATABASE_URL",
        "postgresql+psycopg://app:secret@database.example:5433/trialops_test",
    )
    monkeypatch.setenv("TRIALOPS_CORS_ORIGINS", '["https://trialops.example"]')

    settings = Settings()

    assert settings.env is RuntimeEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+psycopg://app:secret@database.example:5433/trialops_test"
    )
    assert settings.cors_origins == ("https://trialops.example",)


def test_settings_accept_deepseek_aliases_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing DeepSeek variable names map into provider-neutral settings."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://provider.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")

    settings = Settings()

    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "test-secret-key"
    assert str(settings.llm_api_key) == "**********"
    assert str(settings.llm_base_url) == "https://provider.example/"
    assert settings.llm_model == "deepseek-flash"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_api_key", SecretStr("   ")),
        ("llm_model", "   "),
        ("llm_model", "deepseek-chat"),
        ("llm_model", "deepseek-reasoner"),
    ],
)
def test_settings_reject_invalid_llm_configuration(field: str, value: object) -> None:
    """Blank secrets and missing or retired model identifiers fail at startup."""
    with pytest.raises(ValidationError):
        Settings(**{field: value})  # type: ignore[arg-type]


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


@pytest.mark.parametrize("cors_origins", [(), ("*",)])
def test_settings_reject_unsafe_cors_origins(cors_origins: tuple[str, ...]) -> None:
    """CORS must name at least one explicit trusted browser origin."""
    with pytest.raises(ValidationError):
        Settings(cors_origins=cors_origins)
