"""Tests for database resource construction."""

import asyncio

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.core.config import RuntimeEnvironment, Settings
from trialops.db.session import DatabaseResources, create_database_resources


def test_database_resources_use_configured_postgresql_database() -> None:
    """The engine uses the validated URL without exposing its password."""
    settings = Settings(
        env=RuntimeEnvironment.TEST,
        database_url=SecretStr("postgresql+psycopg://app:very-secret@db.example:5433/test_db"),
    )

    database = create_database_resources(settings)

    assert isinstance(database, DatabaseResources)
    assert database.engine.url.drivername == "postgresql+psycopg"
    assert database.engine.url.host == "db.example"
    assert database.engine.url.port == 5433
    assert database.engine.url.database == "test_db"
    assert "very-secret" not in str(database.engine.url)

    asyncio.run(database.dispose())


def test_session_factory_creates_independent_async_sessions() -> None:
    """Each factory call returns a separate unit of database work."""
    database = create_database_resources(Settings(env=RuntimeEnvironment.TEST))

    first_session = database.session_factory()
    second_session = database.session_factory()

    assert isinstance(first_session, AsyncSession)
    assert isinstance(second_session, AsyncSession)
    assert first_session is not second_session

    async def close_resources() -> None:
        await first_session.close()
        await second_session.close()
        await database.dispose()

    asyncio.run(close_resources())
